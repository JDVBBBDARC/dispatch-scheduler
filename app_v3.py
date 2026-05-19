import os, io, socket, calendar
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# ── FIREBASE SETUP ─────────────────────────────────────────────────────────
try:
    import firebase_admin
    from firebase_admin import credentials as fb_credentials, db as fb_db
    _fb_key = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'dispatch-scheduler-ce39f-firebase-adminsdk-fbsvc-affa3531e0.json')
    if not firebase_admin._apps and os.path.exists(_fb_key):
        firebase_admin.initialize_app(
            fb_credentials.Certificate(_fb_key),
            {'databaseURL': 'https://dispatch-scheduler-ce39f-default-rtdb.firebaseio.com/'}
        )
    FIREBASE_OK = True
except Exception as _fb_err:
    FIREBASE_OK = False
    print(f"[Firebase] init skipped: {_fb_err}")

def firebase_notify(event='update'):
    """Push a tiny timestamp to Firebase so all browsers know to refresh."""
    if not FIREBASE_OK:
        return
    try:
        fb_db.reference('dispatch_updates').set({
            'ts': int(datetime.utcnow().timestamp() * 1000),
            'event': event
        })
    except Exception as e:
        print(f"[Firebase] notify failed: {e}")

PH_TZ = ZoneInfo('Asia/Manila')

def ph_now():
    """Current datetime in Philippine time."""
    return datetime.now(PH_TZ)

def ph_today():
    """Current date in Philippine time."""
    return ph_now().date()
from flask import (Flask, render_template, request, redirect, url_for,
                   jsonify, session, flash, send_file)
from models_v2 import (db, TruckTypeDef, Wave, TripRecord,
                       Driver, Helper, Product, Client, Dispatcher, Plate,
                       ChangeLog, Attendance, HelperAttendance, BreakdownLog, AppSetting,
                       CartrackTruckState, CartrackEvent,
                       CartrackGeofence, SiteVisit, TruckCycle,
                       TRUCK_TYPES_SEED, STATUSES,
                       ATTENDANCE_STATUSES, BREAKDOWN_STATUSES, TRIP_TYPES,
                       DOC_HEADER_DEFAULTS, SHEETS_WEBHOOK_KEY, SHEETS_WEBHOOK_DEFAULT,
                       FULL_DAY_PRODUCTS_SEED, FULL_DAY_KEYWORDS, is_product_full_day)
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Support configurable DB path for cloud deployment (e.g. Render persistent disk at /var/data)
DB_PATH = os.environ.get('DB_PATH', os.path.join(BASE_DIR, 'dispatch.db'))

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{DB_PATH}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Use SECRET_KEY env variable in production; fallback for local dev
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dispatch-scheduler-2026')
db.init_app(app)

# ── AUTH BLUEPRINT ─────────────────────────────────────────────────────────
from auth import auth_bp                              # noqa: E402
from auth.routes import login_required, check_can_delete  # noqa: E402
app.register_blueprint(auth_bp)


# ── HELPERS ────────────────────────────────────────────────────────────────
def parse_date(s):
    try:    return date.fromisoformat(s)
    except: return ph_today()

def get_user():
    return session.get('user_name', 'Dispatcher')

def log_change(action, entity='trip'):
    db.session.add(ChangeLog(user_name=get_user(), action=action, entity=entity))
    firebase_notify(entity)

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '127.0.0.1'

def master_lists():
    """Return all master data lists for template use."""
    return dict(
        all_drivers     = Driver.query.filter_by(active=True).order_by(Driver.name).all(),
        all_helpers     = Helper.query.filter_by(active=True).order_by(Helper.name).all(),
        all_products    = Product.query.filter_by(active=True).order_by(Product.name).all(),
        all_clients     = Client.query.filter_by(active=True).order_by(Client.name).all(),
        all_dispatchers = Dispatcher.query.filter_by(active=True).order_by(Dispatcher.name).all(),
        all_plates      = Plate.query.filter_by(active=True).order_by(Plate.plate_no).all(),
        truck_types     = TruckTypeDef.query.order_by(TruckTypeDef.sort_order).all(),
    )

@app.context_processor
def inject_globals():
    doc = {k: AppSetting.get(k, v) for k, v in DOC_HEADER_DEFAULTS.items()}
    return dict(
        now=ph_now(),
        today=ph_today(),
        timedelta=timedelta,
        statuses=STATUSES,
        current_user=get_user(),
        current_user_role=session.get('user_role', ''),
        local_ip=get_local_ip(),
        doc=doc,
    )


# ── INDEX ──────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return redirect(url_for('schedule', date_str=ph_today().isoformat()))


# ── SCHEDULE ───────────────────────────────────────────────────────────────
@app.route('/schedule/<date_str>')
@login_required
def schedule(date_str):
    d = parse_date(date_str)
    truck_types = TruckTypeDef.query.order_by(TruckTypeDef.sort_order).all()

    # Build schedule map: {truck_type_code: [Wave, ...]}
    schedule_map = {}
    for tt in truck_types:
        waves = (Wave.query
                 .filter_by(date=d, truck_type_id=tt.id)
                 .order_by(Wave.wave_number).all())
        schedule_map[tt.code] = waves

    # Counts for tab badges
    counts = {}
    for tt in truck_types:
        cnt = (db.session.query(db.func.count(TripRecord.id))
               .join(Wave)
               .filter(Wave.date == d, Wave.truck_type_id == tt.id)
               .scalar() or 0)
        counts[tt.code] = cnt

    doc = {k: AppSetting.get(k, v) for k, v in DOC_HEADER_DEFAULTS.items()}
    return render_template('schedule/daily.html',
        d=d, schedule_map=schedule_map, counts=counts,
        trip_types=TRIP_TYPES, doc=doc,
        **master_lists())


# ── API: WAVES ─────────────────────────────────────────────────────────────
@app.route('/api/wave/add', methods=['POST'])
def api_wave_add():
    data          = request.get_json()
    date_str      = data.get('date')
    truck_code    = data.get('truck_code')
    d             = parse_date(date_str)
    tt            = TruckTypeDef.query.filter_by(code=truck_code).first_or_404()

    # next wave number
    last = (Wave.query.filter_by(date=d, truck_type_id=tt.id)
            .order_by(Wave.wave_number.desc()).first())
    next_num = (last.wave_number + 1) if last else 1

    wave = Wave(date=d, truck_type_id=tt.id, wave_number=next_num)
    db.session.add(wave)
    db.session.commit()
    log_change(f"Added {wave.label} for {tt.name} on {d}", 'wave')
    db.session.commit()

    return jsonify({'wave_id': wave.id, 'wave_number': next_num, 'label': wave.label})


@app.route('/api/wave/<int:wid>/delete', methods=['POST'])
def api_wave_delete(wid):
    if not check_can_delete():
        return jsonify({'error': 'You do not have permission to delete.'}), 403
    wave = Wave.query.get_or_404(wid)
    info = f"{wave.label} ({wave.truck_type.name}) on {wave.date}"
    db.session.delete(wave)
    log_change(f"Deleted {info}", 'wave')
    db.session.commit()
    return jsonify({'ok': True})


# ── API: TRIPS ──────────────────────────────────────────────────────────────
@app.route('/api/trip/save', methods=['POST'])
def api_trip_save():
    data     = request.get_json()
    trip_id  = data.get('trip_id')
    wave_id  = data.get('wave_id')

    if trip_id:
        trip = TripRecord.query.get_or_404(trip_id)
    else:
        # new row — get next trip number
        last = (TripRecord.query.filter_by(wave_id=wave_id)
                .order_by(TripRecord.trip_number.desc()).first())
        trip = TripRecord(wave_id=wave_id,
                          trip_number=(last.trip_number + 1 if last else 1))
        db.session.add(trip)

    # Apply all provided fields
    field_map = {
        'driver_id': ('driver_id', int),
        'helper_id': ('helper_id', int),
        'plate_id':  ('plate_id',  int),
        'product_id':('product_id',int),
        'client_id': ('client_id', int),
        'dispatcher_id':('dispatcher_id',int),
        'trip_type':       ('trip_type',       str),
        'rs_no':           ('rs_no',           str),
        'po_no':           ('po_no',           str),
        'reference':       ('reference',       str),
        'dr_no':           ('dr_no',           str),
        'volume':          ('volume',          str),
        'status':          ('status',          str),
        'toll_fee':        ('toll_fee',        float),
        'toll_expressway': ('toll_expressway', str),
        'toll_entry':      ('toll_entry',      str),
        'toll_exit':       ('toll_exit',       str),
        'toll_class':      ('toll_class',      str),
        'notes':           ('notes',           str),
    }
    for key, (attr, cast) in field_map.items():
        if key in data:
            val = data[key]
            if val == '' or val is None:
                setattr(trip, attr, None)
            else:
                try:
                    setattr(trip, attr, cast(val))
                except (ValueError, TypeError):
                    setattr(trip, attr, None)

    trip.updated_by = get_user()
    trip.updated_at = datetime.utcnow()
    db.session.commit()

    wave = Wave.query.get(trip.wave_id)
    log_change(
        f"Saved trip #{trip.trip_number} in {wave.label} "
        f"({wave.truck_type.name}) on {wave.date}", 'trip')
    db.session.commit()

    return jsonify(trip.to_dict())


@app.route('/api/trip/<int:tid>/delete', methods=['POST'])
def api_trip_delete(tid):
    if not check_can_delete():
        return jsonify({'error': 'You do not have permission to delete.'}), 403
    trip = TripRecord.query.get_or_404(tid)
    wave = trip.wave
    info = f"trip #{trip.trip_number} in {wave.label} ({wave.truck_type.name}) on {wave.date}"
    db.session.delete(trip)
    log_change(f"Deleted {info}", 'trip')
    db.session.commit()
    return jsonify({'ok': True})


# ── DASHBOARD KPI REFRESH API ──────────────────────────────────────────────
@app.route('/api/dashboard/kpis')
@login_required
def api_dashboard_kpis():
    """Lightweight endpoint for live KPI card refresh (called by Firebase listener)."""
    from_date = request.args.get('trend_start', (ph_today() - timedelta(days=13)).isoformat())
    to_date   = request.args.get('trend_end',   ph_today().isoformat())
    truck     = request.args.get('truck',  'all')
    status    = request.args.get('status', 'all')
    from_d = parse_date(from_date)
    to_d   = parse_date(to_date)
    q = (db.session.query(TripRecord).join(Wave)
         .filter(Wave.date >= from_d, Wave.date <= to_d))
    if truck != 'all':
        tt = TruckTypeDef.query.filter_by(code=truck).first()
        if tt:
            q = q.filter(Wave.truck_type_id == tt.id)
    if status != 'all':
        q = q.filter(TripRecord.status == status)
    trips = q.all()
    # Total breakdown hours within range (uses started_at)
    bd_from_dt = datetime.combine(from_d, datetime.min.time())
    bd_to_dt   = datetime.combine(to_d,   datetime.max.time())
    bd_logs = (db.session.query(BreakdownLog)
               .filter(BreakdownLog.started_at.isnot(None),
                       BreakdownLog.ended_at.isnot(None),
                       BreakdownLog.started_at >= bd_from_dt,
                       BreakdownLog.started_at <= bd_to_dt)
               .all())
    total_breakdown_hours = round(sum(b.duration_hours for b in bd_logs), 1)
    return jsonify({
        'total':                 len(trips),
        'by_status':             {s: sum(1 for t in trips if t.status == s) for s in STATUSES},
        'total_toll_fee':        sum((t.toll_fee or 0) for t in trips if t.status != 'Canceled'),
        'total_breakdown_hours': total_breakdown_hours,
    })


# ── FLEET UTILIZATION API ──────────────────────────────────────────────────
@app.route('/api/dashboard/fleet-utilization')
@login_required
def api_dashboard_fleet_utilization():
    """
    Compute fleet utilization % per truck type per day for the requested range.

    Scoring rules (configurable per truck type):
      - point_per_leg       = points awarded per delivered trip leg (0.5 for 10W)
      - daily_target_points = daily 100% threshold (4.0 for 10W, 1.5 for others)

    Special-case: trips whose product has is_full_day_trip = True count for the
    truck type's full daily_target_points instead of point_per_leg
    (e.g., ASPHALT runs).

    Active truck count per type = active plates assigned to that type.
    """
    from_date = request.args.get('trend_start',
                                 (ph_today() - timedelta(days=13)).isoformat())
    to_date   = request.args.get('trend_end', ph_today().isoformat())
    from_d = parse_date(from_date)
    to_d   = parse_date(to_date)
    if from_d > to_d:
        from_d, to_d = to_d, from_d

    truck_types = TruckTypeDef.query.order_by(TruckTypeDef.sort_order).all()

    # Active truck count per type (active plates only)
    plate_counts = dict(
        db.session.query(Plate.truck_type_id, db.func.count(Plate.id))
                  .filter(Plate.active == True, Plate.truck_type_id.isnot(None))
                  .group_by(Plate.truck_type_id).all()
    )

    # Fetch all delivered trips in range with their wave + product info
    trips = (db.session.query(TripRecord, Wave)
             .join(Wave, TripRecord.wave_id == Wave.id)
             .filter(Wave.date >= from_d, Wave.date <= to_d,
                     TripRecord.status == 'Delivered')
             .all())

    # Build product → is_full_day map (only for products that appear in the trips).
    # A product is "full-day" if EITHER:
    #   - its is_full_day_trip flag is True, OR
    #   - its name contains a FULL_DAY_KEYWORDS substring (e.g., "asphalt",
    #     case-insensitive — covers "ASPHALT", "Asphalt Plant", "Asphalt Mix"...).
    product_ids = {t.product_id for (t, _w) in trips if t.product_id}
    full_day_products = set()
    if product_ids:
        for prod in Product.query.filter(Product.id.in_(product_ids)).all():
            if is_product_full_day(prod):
                full_day_products.add(prod.id)

    # Build day list
    days = []
    cur = from_d
    while cur <= to_d:
        days.append(cur)
        cur += timedelta(days=1)

    # Aggregate points per (truck_type_id, day)
    points_map = {tt.id: {d: 0.0 for d in days} for tt in truck_types}
    for trip, wave in trips:
        if not wave or wave.truck_type_id not in points_map:
            continue
        tt = next((x for x in truck_types if x.id == wave.truck_type_id), None)
        if not tt:
            continue
        if trip.product_id and trip.product_id in full_day_products:
            pts = float(tt.daily_target_points or 1.5)
        else:
            pts = float(tt.point_per_leg or 1.0)
        if wave.date in points_map[tt.id]:
            points_map[tt.id][wave.date] += pts

    # Build series per truck type
    series = []
    for tt in truck_types:
        truck_count   = plate_counts.get(tt.id, 0)
        target_per_truck = float(tt.daily_target_points or 1.5)
        max_per_day   = truck_count * target_per_truck if truck_count > 0 else 0
        daily_pts     = [points_map[tt.id][d] for d in days]
        daily_util    = [(p / max_per_day * 100.0) if max_per_day > 0 else 0.0
                         for p in daily_pts]
        series.append({
            'code':              tt.code,
            'name':              tt.name,
            'color':             tt.color,
            'point_per_leg':     float(tt.point_per_leg or 1.0),
            'daily_target':      target_per_truck,
            'truck_count':       truck_count,
            'max_per_day':       max_per_day,
            'points':            [round(v, 2) for v in daily_pts],
            'util_pct':          [round(v, 2) for v in daily_util],
        })

    return jsonify({
        'days':        [d.strftime('%b %d') for d in days],
        'days_iso':    [d.isoformat() for d in days],
        'series':      series,
    })


# ── BREAKDOWN HOURS KPI API ────────────────────────────────────────────────
@app.route('/api/dashboard/breakdown-hours')
@login_required
def api_dashboard_breakdown_hours():
    """
    Total accumulated breakdown hours within the date range, grouped by plate.

    Inclusion rule: a BreakdownLog counts toward the KPI if it has BOTH
    started_at and ended_at populated, and started_at falls within the range.
    Older records without timestamps are excluded (you can't compute hours).
    """
    from_date = request.args.get('trend_start',
                                 (ph_today() - timedelta(days=13)).isoformat())
    to_date   = request.args.get('trend_end', ph_today().isoformat())
    from_d = parse_date(from_date)
    to_d   = parse_date(to_date)
    if from_d > to_d:
        from_d, to_d = to_d, from_d

    from_dt = datetime.combine(from_d, datetime.min.time())
    to_dt   = datetime.combine(to_d,   datetime.max.time())

    rows = (db.session.query(BreakdownLog)
            .filter(BreakdownLog.started_at.isnot(None),
                    BreakdownLog.ended_at.isnot(None),
                    BreakdownLog.started_at >= from_dt,
                    BreakdownLog.started_at <= to_dt)
            .all())

    by_plate = {}
    for log in rows:
        if not log.plate_id:
            continue
        hrs = log.duration_hours
        if hrs <= 0:
            continue
        plate = log.plate
        key = log.plate_id
        if key not in by_plate:
            by_plate[key] = {
                'plate_id':       log.plate_id,
                'plate_display':  plate.display if plate else 'Unknown',
                'truck_type':     plate.truck_type.name if (plate and plate.truck_type) else 'Unassigned',
                'truck_color':    plate.truck_type.color if (plate and plate.truck_type) else '#999',
                'total_hours':    0.0,
                'job_orders':     [],
            }
        by_plate[key]['total_hours'] += hrs
        by_plate[key]['job_orders'].append({
            'id':            log.id,
            'started_at':    log.started_at.strftime('%Y-%m-%d %H:%M'),
            'ended_at':      log.ended_at.strftime('%Y-%m-%d %H:%M') if log.ended_at else '',
            'hours':         round(hrs, 2),
            'description':   log.description or '',
            'status':        log.status or '',
            'remarks':       log.remarks or '',
        })

    # Sort plates by total_hours desc
    plates_list = sorted(by_plate.values(),
                         key=lambda p: p['total_hours'], reverse=True)
    for p in plates_list:
        p['total_hours'] = round(p['total_hours'], 2)
        # Sort each plate's job orders by start time desc (most recent first)
        p['job_orders'].sort(key=lambda jo: jo['started_at'], reverse=True)

    total_hours = round(sum(p['total_hours'] for p in plates_list), 2)
    total_jobs  = sum(len(p['job_orders']) for p in plates_list)

    return jsonify({
        'total_hours':    total_hours,
        'total_jobs':     total_jobs,
        'plate_count':    len(plates_list),
        'by_plate':       plates_list,
    })


# ── DRIVER / TRUCK RATIO API ───────────────────────────────────────────────
@app.route('/api/dashboard/driver-truck-ratio')
@login_required
def api_dashboard_driver_truck_ratio():
    """
    Daily breakdown of working trucks vs present drivers.

    Working Trucks  = active plates of selected truck type(s) - plates currently
                      under repair on that day (BreakdownLog with status='Under
                      Repair' covering the date, i.e., date <= D AND
                      (resolved_date IS NULL OR resolved_date > D)).
    Present Drivers = WHEN no truck-type filter: distinct drivers with
                      attendance.status='Present' that day (system-wide).
                      WHEN filtered: distinct drivers who ACTUALLY drove a truck
                      of one of the selected types that day (from TripRecord,
                      excluding 'Canceled' trips). This works even if a driver
                      is qualified for multiple types — they're counted under
                      the type they actually used that day. The API also returns
                      per-day driver→truck assignments so the UI can show which
                      driver drove which unit.
    Coverage Ratio  = Present Drivers / Working Trucks (0 if no working trucks).
    Driver Shortage = max(0, Working Trucks - Present Drivers).

    Query params:
        trend_start, trend_end – date range (defaults to last 14 days)
        truck_types – comma-separated list of truck-type codes, e.g., '10W,12W'
                      (omit or empty = all)
    """
    from_date = request.args.get('trend_start',
                                 (ph_today() - timedelta(days=13)).isoformat())
    to_date   = request.args.get('trend_end', ph_today().isoformat())
    raw_codes = request.args.get('truck_types', '').strip()
    selected_codes = [c.strip() for c in raw_codes.split(',') if c.strip()]

    from_d = parse_date(from_date)
    to_d   = parse_date(to_date)
    if from_d > to_d:
        from_d, to_d = to_d, from_d

    # Resolve truck-type codes -> ids (skip unknown codes silently)
    selected_tt_ids = set()
    if selected_codes:
        selected_tt_ids = {
            tt.id for tt in TruckTypeDef.query.filter(
                TruckTypeDef.code.in_(selected_codes)).all()
        }

    # Day list
    days = []
    cur = from_d
    while cur <= to_d:
        days.append(cur)
        cur += timedelta(days=1)

    # Active plates (filtered by truck type if requested)
    plates_q = Plate.query.filter_by(active=True)
    if selected_tt_ids:
        plates_q = plates_q.filter(Plate.truck_type_id.in_(selected_tt_ids))
    active_plate_ids = {p.id for p in plates_q.all()}
    total_active_plates = len(active_plate_ids)

    # Pre-fetch breakdowns for ONLY plates we care about
    breakdown_q = db.session.query(
            BreakdownLog.plate_id, BreakdownLog.date, BreakdownLog.resolved_date
        ).filter(BreakdownLog.status == 'Under Repair',
                 BreakdownLog.date <= to_d)
    if active_plate_ids:
        breakdown_q = breakdown_q.filter(BreakdownLog.plate_id.in_(active_plate_ids))
    breakdowns = breakdown_q.all()

    # Drivers present per day:
    # If no filter: system-wide attendance count.
    # If filtered: drivers who actually drove a truck of selected type(s) that day.
    drivers_per_day = {}
    assignments_per_day = {}   # date -> [{driver, plate, body, type_code, type_color}, ...]

    if not selected_tt_ids:
        attn_rows = (db.session.query(Attendance.date,
                                      db.func.count(db.distinct(Attendance.driver_id)))
                     .filter(Attendance.status == 'Present',
                             Attendance.date >= from_d,
                             Attendance.date <= to_d)
                     .group_by(Attendance.date).all())
        drivers_per_day = {row[0]: row[1] for row in attn_rows}
    else:
        # Detect ACTUAL usage from TripRecords. A driver who is qualified for
        # both 10W and 12W but drove a 12W truck that day counts under 12W,
        # not 10W (we look at what they actually used).
        trip_rows = (db.session.query(
                        Wave.date,
                        TripRecord.driver_id,
                        Driver.name,
                        Plate.id, Plate.plate_no, Plate.body_no,
                        TruckTypeDef.code, TruckTypeDef.color, TruckTypeDef.name,
                    )
                     .join(TripRecord, TripRecord.wave_id == Wave.id)
                     .join(Driver,    Driver.id    == TripRecord.driver_id)
                     .outerjoin(Plate, Plate.id    == TripRecord.plate_id)
                     .join(TruckTypeDef, TruckTypeDef.id == Wave.truck_type_id)
                     .filter(Wave.date >= from_d, Wave.date <= to_d,
                             Wave.truck_type_id.in_(selected_tt_ids),
                             TripRecord.driver_id.isnot(None),
                             TripRecord.status != 'Canceled')
                     .distinct()
                     .all())
        # Build per-day distinct-driver count + assignment list
        per_day_drivers = {}
        for d_date, drv_id, drv_name, plate_id, plate_no, body_no, tt_code, tt_color, tt_name in trip_rows:
            per_day_drivers.setdefault(d_date, set()).add(drv_id)
            display = (f"{body_no} / {plate_no}" if body_no else plate_no) if plate_no else '—'
            assignments_per_day.setdefault(d_date, []).append({
                'driver':    drv_name,
                'plate':     display,
                'type_code': tt_code,
                'type_name': tt_name,
                'type_color': tt_color,
            })
        drivers_per_day = {d: len(s) for d, s in per_day_drivers.items()}

    working = []
    present = []
    ratios  = []
    shortages = []
    for d in days:
        # A breakdown is "active on D" if start_date <= D AND (resolved_date IS NULL OR resolved_date > D)
        broken_plate_ids = {
            b.plate_id for b in breakdowns
            if b.date <= d and (b.resolved_date is None or b.resolved_date > d)
        }
        wt = max(0, total_active_plates - len(broken_plate_ids))
        pd = drivers_per_day.get(d, 0)
        rt = round((pd / wt), 3) if wt > 0 else 0
        sh = max(0, wt - pd)
        working.append(wt)
        present.append(pd)
        ratios.append(rt)
        shortages.append(sh)

    return jsonify({
        'days':            [d.strftime('%b %d') for d in days],
        'days_iso':        [d.isoformat() for d in days],
        'working_trucks':  working,
        'present_drivers': present,
        'coverage_ratio':  ratios,
        'driver_shortage': shortages,
        'total_plates':    total_active_plates,
        'selected_codes':  selected_codes,
        'driver_source':   'attendance' if not selected_tt_ids else 'trips',
        # Per-day driver→truck assignments (only when filtered).
        # Deduped: a driver who did multiple trips on the same truck shows once.
        'assignments':     {
            d.isoformat(): _dedupe_assignments(rows)
            for d, rows in assignments_per_day.items()
        },
    })


def _dedupe_assignments(rows):
    """Collapse identical (driver, plate) pairs that come from multiple trips."""
    seen = set()
    out = []
    for r in rows:
        key = (r['driver'], r['plate'], r['type_code'])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


# ── DASHBOARD ──────────────────────────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    from collections import defaultdict
    filter_date  = request.args.get('date',  ph_today().isoformat())
    filter_truck = request.args.get('truck', 'all')
    filter_status= request.args.get('status','all')
    trend_end_str   = request.args.get('trend_end',   ph_today().isoformat())
    trend_start_str = request.args.get('trend_start', (ph_today() - timedelta(days=13)).isoformat())
    trend_end_d     = parse_date(trend_end_str)
    trend_start_d   = parse_date(trend_start_str)
    if trend_start_d > trend_end_d:
        trend_start_d, trend_end_d = trend_end_d, trend_start_d
    d = parse_date(filter_date)

    truck_types = TruckTypeDef.query.order_by(TruckTypeDef.sort_order).all()

    # Base query for the selected date range
    q = (db.session.query(TripRecord)
         .join(Wave)
         .filter(Wave.date >= trend_start_d, Wave.date <= trend_end_d))
    if filter_truck != 'all':
        tt = TruckTypeDef.query.filter_by(code=filter_truck).first()
        if tt:
            q = q.filter(Wave.truck_type_id == tt.id)
    if filter_status != 'all':
        q = q.filter(TripRecord.status == filter_status)

    trips = q.all()

    # Stats
    total          = len(trips)
    by_status      = {s: sum(1 for t in trips if t.status == s) for s in STATUSES}
    total_toll_fee = sum((t.toll_fee or 0) for t in trips if t.status != 'Canceled')
    # Breakdown hours within the trend range (accumulate completed J.O.s)
    _bd_from_dt = datetime.combine(trend_start_d, datetime.min.time())
    _bd_to_dt   = datetime.combine(trend_end_d,   datetime.max.time())
    _bd_logs = (db.session.query(BreakdownLog)
                .filter(BreakdownLog.started_at.isnot(None),
                        BreakdownLog.ended_at.isnot(None),
                        BreakdownLog.started_at >= _bd_from_dt,
                        BreakdownLog.started_at <= _bd_to_dt)
                .all())
    total_breakdown_hours = round(sum(b.duration_hours for b in _bd_logs), 1)
    by_truck    = {}
    for tt in truck_types:
        cnt = sum(1 for t in trips
                  if t.wave and t.wave.truck_type_id == tt.id)
        by_truck[tt.code] = {'name': tt.name, 'color': tt.color, 'count': cnt}

    # Trend — total (iterate day by day over selected range)
    trend_days, trend_counts = [], []
    cur = trend_start_d
    while cur <= trend_end_d:
        cnt = (db.session.query(db.func.count(TripRecord.id))
               .join(Wave).filter(Wave.date == cur).scalar() or 0)
        trend_days.append(cur.strftime('%b %d'))
        trend_counts.append(cnt)
        cur += timedelta(days=1)

    # Trend per truck type
    trend_by_truck = []
    for tt in truck_types:
        day_counts = []
        cur = trend_start_d
        while cur <= trend_end_d:
            cnt = (db.session.query(db.func.count(TripRecord.id))
                   .join(Wave)
                   .filter(Wave.date == cur, Wave.truck_type_id == tt.id)
                   .scalar() or 0)
            day_counts.append(cnt)
            cur += timedelta(days=1)
        trend_by_truck.append({
            'code': tt.code, 'name': tt.name,
            'color': tt.color, 'counts': day_counts
        })

    # Recent changes
    recent_changes = (ChangeLog.query.order_by(ChangeLog.timestamp.desc()).limit(8).all())

    # Top drivers by delivered trips — selected date range
    _drv = defaultdict(lambda: defaultdict(lambda: {'name': '', 'total': 0, 'delivered': 0}))
    all_tr = (db.session.query(TripRecord).join(Wave)
              .filter(TripRecord.driver_id.isnot(None),
                      Wave.date >= trend_start_d, Wave.date <= trend_end_d).all())
    for t in all_tr:
        if t.wave and t.driver:
            s = _drv[t.wave.truck_type_id][t.driver_id]
            s['name'] = t.driver.name
            s['total'] += 1
            if t.status == 'Delivered':
                s['delivered'] += 1

    top_drivers_by_truck = []
    for tt in truck_types:
        drivers = sorted(_drv.get(tt.id, {}).values(),
                         key=lambda x: x['delivered'], reverse=True)[:5]
        drivers = [d for d in drivers if d['total'] > 0 and d['name']]
        if drivers:
            top_drivers_by_truck.append({
                'truck': tt.name, 'code': tt.code,
                'color': tt.color, 'drivers': drivers
            })

    # Top absent drivers — selected date range
    absent_stats = (db.session.query(
                        Driver.name,
                        db.func.count(Attendance.id).label('cnt')
                    )
                    .join(Attendance, Attendance.driver_id == Driver.id)
                    .filter(Attendance.status == 'Absent',
                            Attendance.date >= trend_start_d,
                            Attendance.date <= trend_end_d)
                    .group_by(Driver.id, Driver.name)
                    .order_by(db.func.count(Attendance.id).desc())
                    .limit(10)
                    .all())
    absent_drivers = [{'name': r[0], 'absences': r[1]} for r in absent_stats]

    return render_template('dashboard_v2.html',
        d=d, filter_date=filter_date,
        filter_truck=filter_truck, filter_status=filter_status,
        trend_start_str=trend_start_str, trend_end_str=trend_end_str,
        truck_types=truck_types, trips=trips,
        total=total, by_status=by_status, by_truck=by_truck, total_toll_fee=total_toll_fee,
        total_breakdown_hours=total_breakdown_hours,
        trend_days=trend_days, trend_counts=trend_counts,
        trend_by_truck=trend_by_truck,
        recent_changes=recent_changes,
        top_drivers_by_truck=top_drivers_by_truck,
        absent_drivers=absent_drivers)


# ── MASTER DATA ────────────────────────────────────────────────────────────
@app.route('/master')
@login_required
def master():
    truck_types = TruckTypeDef.query.order_by(TruckTypeDef.sort_order).all()
    drivers     = Driver.query.order_by(Driver.name).all()
    helpers     = Helper.query.order_by(Helper.name).all()
    products    = Product.query.order_by(Product.name).all()
    clients     = Client.query.order_by(Client.name).all()
    dispatchers = Dispatcher.query.order_by(Dispatcher.name).all()
    plates      = Plate.query.order_by(Plate.truck_type_id, Plate.plate_no).all()
    return render_template('master/index.html',
        truck_types=truck_types,
        drivers=drivers, helpers=helpers, products=products,
        clients=clients, dispatchers=dispatchers, plates=plates,
        full_day_keywords=FULL_DAY_KEYWORDS)


@app.route('/api/master/<category>/add', methods=['POST'])
def api_master_add(category):
    data = request.get_json()
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name required'}), 400

    model_map = {'drivers': Driver, 'helpers': Helper,
                 'products': Product, 'clients': Client,
                 'dispatchers': Dispatcher}
    if category == 'plates':
        plate_no = name
        body_no  = (data.get('body_no') or '').strip()
        ttid     = data.get('truck_type_id') or None
        if ttid: ttid = int(ttid)
        obj = Plate(plate_no=plate_no, body_no=body_no or None, truck_type_id=ttid)
        db.session.add(obj)
        db.session.commit()
        log_change(f"Added plate {obj.display}", 'master')
        db.session.commit()
        tt = TruckTypeDef.query.get(ttid) if ttid else None
        return jsonify({'id': obj.id, 'display': obj.display,
                        'truck_type': tt.name if tt else ''})

    Model = model_map.get(category)
    if not Model:
        return jsonify({'error': 'Unknown category'}), 400
    obj = Model(name=name)
    # Drivers can be qualified for multiple truck types
    if category == 'drivers':
        tt_ids = data.get('truck_type_ids') or []
        if isinstance(tt_ids, list) and tt_ids:
            tts = TruckTypeDef.query.filter(TruckTypeDef.id.in_(tt_ids)).all()
            obj.truck_types = tts
    db.session.add(obj)
    db.session.commit()
    log_change(f"Added {category[:-1]} '{name}'", 'master')
    db.session.commit()
    resp = {'id': obj.id, 'name': obj.name}
    if category == 'drivers':
        resp['truck_type_ids'] = [t.id for t in obj.truck_types]
    return jsonify(resp)


@app.route('/api/master/<category>/<int:item_id>/update', methods=['POST'])
def api_master_update(category, item_id):
    data = request.get_json()
    model_map = {'drivers': Driver, 'helpers': Helper,
                 'products': Product, 'clients': Client,
                 'dispatchers': Dispatcher, 'plates': Plate}
    Model = model_map.get(category)
    if not Model:
        return jsonify({'error': 'Unknown'}), 400
    obj = Model.query.get_or_404(item_id)
    if category == 'plates':
        obj.plate_no = (data.get('plate_no') or obj.plate_no).strip()
        obj.body_no  = (data.get('body_no') or '').strip() or None
        ttid = data.get('truck_type_id') or None
        obj.truck_type_id = int(ttid) if ttid else None
    else:
        obj.name = (data.get('name') or obj.name).strip()
        # Products: optional is_full_day_trip toggle
        if category == 'products' and 'is_full_day_trip' in data:
            obj.is_full_day_trip = bool(data.get('is_full_day_trip'))
        # Drivers: optional list of truck-type categories (many-to-many)
        if category == 'drivers' and 'truck_type_ids' in data:
            tt_ids = data.get('truck_type_ids') or []
            if isinstance(tt_ids, list):
                tts = (TruckTypeDef.query.filter(TruckTypeDef.id.in_(tt_ids)).all()
                       if tt_ids else [])
                obj.truck_types = tts
                # Keep legacy single-category column in sync (use first selection
                # as the "primary" — or NULL when none selected)
                obj.truck_type_id = tts[0].id if tts else None
    db.session.commit()
    log_change(f"Updated {category[:-1]} id={item_id}", 'master')
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/master/truck-type/<int:tt_id>/update', methods=['POST'])
@login_required
def api_truck_type_update(tt_id):
    """Update fleet-utilization scoring fields for a truck type."""
    data = request.get_json() or {}
    tt = TruckTypeDef.query.get_or_404(tt_id)
    if 'point_per_leg' in data:
        try:
            tt.point_per_leg = float(data['point_per_leg'])
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid point_per_leg'}), 400
    if 'daily_target_points' in data:
        try:
            tt.daily_target_points = float(data['daily_target_points'])
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid daily_target_points'}), 400
    db.session.commit()
    log_change(f"Updated truck type {tt.code} scoring (pts/leg={tt.point_per_leg}, target={tt.daily_target_points})", 'master')
    db.session.commit()
    return jsonify({'ok': True, 'point_per_leg': tt.point_per_leg,
                    'daily_target_points': tt.daily_target_points})


@app.route('/api/master/<category>/<int:item_id>/toggle', methods=['POST'])
def api_master_toggle(category, item_id):
    if not check_can_delete():
        return jsonify({'error': 'You do not have permission to deactivate records.'}), 403
    model_map = {'drivers': Driver, 'helpers': Helper,
                 'products': Product, 'clients': Client,
                 'dispatchers': Dispatcher, 'plates': Plate}
    Model = model_map.get(category)
    if not Model:
        return jsonify({'error': 'Unknown'}), 400
    obj = Model.query.get_or_404(item_id)
    obj.active = not obj.active
    db.session.commit()
    return jsonify({'active': obj.active})


# ── REPORTS ────────────────────────────────────────────────────────────────
@app.route('/reports')
@login_required
def reports():
    year        = request.args.get('year',  ph_today().year,  type=int)
    month       = request.args.get('month', ph_today().month, type=int)
    filter_truck= request.args.get('truck', 'all')
    truck_types = TruckTypeDef.query.order_by(TruckTypeDef.sort_order).all()

    last_day    = calendar.monthrange(year, month)[1]
    mo_s        = date(year, month, 1)
    mo_e        = date(year, month, last_day)

    q = (db.session.query(TripRecord).join(Wave)
         .filter(Wave.date >= mo_s, Wave.date <= mo_e))
    if filter_truck != 'all':
        tt = TruckTypeDef.query.filter_by(code=filter_truck).first()
        if tt: q = q.filter(Wave.truck_type_id == tt.id)
    trips = q.order_by(Wave.date, Wave.wave_number, TripRecord.trip_number).all()

    by_status = {s: sum(1 for t in trips if t.status == s) for s in STATUSES}
    years     = list(range(2024, ph_today().year + 2))

    return render_template('reports/index.html',
        year=year, month=month, years=years,
        filter_truck=filter_truck, truck_types=truck_types,
        trips=trips, by_status=by_status, mo_s=mo_s)


@app.route('/reports/export')
def export():
    year        = request.args.get('year',  ph_today().year,  type=int)
    month       = request.args.get('month', ph_today().month, type=int)
    filter_truck= request.args.get('truck', 'all')
    last_day    = calendar.monthrange(year, month)[1]
    mo_s        = date(year, month, 1)
    mo_e        = date(year, month, last_day)
    truck_types = TruckTypeDef.query.order_by(TruckTypeDef.sort_order).all()

    MAROON  = '8B1A2B'; WHITE = 'FFFFFF'; LGRAY = 'F5F0F0'
    GRN     = 'C6EFCE'; RED   = 'FFB3B3'; YEL   = 'FFF2CC'; BLU   = 'DDEEFF'

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # remove default sheet

    def hdr_style(cell, bg=MAROON, fg=WHITE, bold=True, sz=10):
        cell.font  = Font(name='Calibri', bold=bold, color=fg, size=sz)
        cell.fill  = PatternFill('solid', fgColor=bg)
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

    def data_style(cell, bg=None):
        cell.font = Font(name='Calibri', size=9)
        cell.alignment = Alignment(vertical='center')
        if bg: cell.fill = PatternFill('solid', fgColor=bg)

    status_colors = {'Delivered': GRN, 'In Transit': YEL, 'Loading': BLU, 'Pending': None}
    col_hdrs = ['Date','Truck Type','Wave','#','Driver','Helper','Plate',
                'Product','Client','Dispatcher','RS No','PO No','Reference',
                'DR No','Volume','Status','Notes','Updated By']

    sheets_to_create = []
    if filter_truck == 'all':
        for tt in truck_types: sheets_to_create.append(tt)
        sheets_to_create.append(None)
    else:
        tt = TruckTypeDef.query.filter_by(code=filter_truck).first()
        if tt: sheets_to_create.append(tt)

    for tt_obj in sheets_to_create:
        sheet_name = tt_obj.name[:28] if tt_obj else 'All Trucks'
        ws = wb.create_sheet(title=sheet_name)

        ws.merge_cells(f'A1:{openpyxl.utils.get_column_letter(len(col_hdrs))}1')
        title_cell = ws['A1']
        mo_label   = mo_s.strftime('%B %Y')
        title_cell.value = f"DISPATCH SCHEDULE — {tt_obj.name if tt_obj else 'ALL TRUCKS'} — {mo_label}"
        hdr_style(title_cell, sz=13)
        ws.row_dimensions[1].height = 26

        for ci, h in enumerate(col_hdrs, 1):
            c = ws.cell(row=2, column=ci, value=h)
            hdr_style(c, bg='5D0E1B', sz=9)
        ws.row_dimensions[2].height = 22

        q2 = (db.session.query(TripRecord).join(Wave)
              .filter(Wave.date >= mo_s, Wave.date <= mo_e))
        if tt_obj: q2 = q2.filter(Wave.truck_type_id == tt_obj.id)
        trip_rows = q2.order_by(Wave.date, Wave.wave_number, TripRecord.trip_number).all()

        for ri, t in enumerate(trip_rows, 3):
            bg = status_colors.get(t.status or '', None)
            vals = [
                t.wave.date.strftime('%Y-%m-%d') if t.wave else '',
                t.wave.truck_type.name if t.wave else '',
                t.wave.label if t.wave else '',
                t.trip_number,
                t.driver.name if t.driver else '',
                t.helper.name if t.helper else '',
                t.plate.display if t.plate else '',
                t.product.name if t.product else '',
                t.client.name if t.client else '',
                t.dispatcher.name if t.dispatcher else '',
                t.rs_no or '', t.po_no or '', t.reference or '',
                t.dr_no or '', t.volume or '',
                t.status or '', t.notes or '',
                t.updated_by or '',
            ]
            for ci, v in enumerate(vals, 1):
                c = ws.cell(row=ri, column=ci, value=v)
                data_style(c, bg=bg)
            if ri % 2 == 0 and not bg:
                for ci in range(1, len(col_hdrs)+1):
                    ws.cell(row=ri, column=ci).fill = PatternFill('solid', fgColor=LGRAY)

        col_widths = [12,18,10,4,16,16,14,18,18,14,10,10,10,10,8,12,20,14]
        for ci, w in enumerate(col_widths, 1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(ci)].width = w
        ws.freeze_panes = 'A3'

    buf = io.BytesIO()
    wb.save(buf); buf.seek(0)
    fname = f"Dispatch_{year}_{month:02d}.xlsx"
    return send_file(buf, as_attachment=True, download_name=fname,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ── ATTENDANCE ─────────────────────────────────────────────────────────────
@app.route('/attendance')
@login_required
def attendance():
    year   = request.args.get('year',  ph_today().year,  type=int)
    month  = request.args.get('month', ph_today().month, type=int)
    years  = list(range(2024, ph_today().year + 2))

    last_day = calendar.monthrange(year, month)[1]
    mo_s     = date(year, month, 1)
    mo_e     = date(year, month, last_day)
    days     = list(range(1, last_day + 1))

    drivers = Driver.query.filter_by(active=True).order_by(Driver.name).all()

    # Build attendance map: {(driver_id, day): status}
    records = (Attendance.query
               .filter(Attendance.date >= mo_s, Attendance.date <= mo_e)
               .all())
    att_map = {}
    for r in records:
        att_map[(r.driver_id, r.date.day)] = r.status

    # Summary per driver
    summary = {}
    for drv in drivers:
        summary[drv.id] = {s: 0 for s in ATTENDANCE_STATUSES}
        for day in days:
            st = att_map.get((drv.id, day))
            if st and st in summary[drv.id]:
                summary[drv.id][st] += 1

    return render_template('attendance/index.html',
        year=year, month=month, years=years,
        mo_s=mo_s, days=days,
        drivers=drivers, att_map=att_map, summary=summary,
        att_statuses=ATTENDANCE_STATUSES)


@app.route('/api/attendance/set', methods=['POST'])
def api_attendance_set():
    data      = request.get_json()
    driver_id = data.get('driver_id')
    date_str  = data.get('date')
    status    = data.get('status')  # None = clear

    if not driver_id or not date_str:
        return jsonify({'error': 'Missing fields'}), 400

    d = parse_date(date_str)
    record = Attendance.query.filter_by(driver_id=driver_id, date=d).first()

    if status is None or status == '':
        # Clear the record
        if record:
            db.session.delete(record)
            db.session.commit()
        return jsonify({'status': '', 'date': date_str, 'driver_id': driver_id})

    if not record:
        record = Attendance(driver_id=driver_id, date=d)
        db.session.add(record)

    record.status     = status
    record.updated_by = get_user()
    record.updated_at = datetime.utcnow()
    db.session.commit()

    drv = Driver.query.get(driver_id)
    log_change(f"Attendance {drv.name if drv else driver_id}: {status} on {d}", 'attendance')
    db.session.commit()

    return jsonify({'status': status, 'date': date_str, 'driver_id': driver_id})


# ── HELPER ATTENDANCE ──────────────────────────────────────────────────────
@app.route('/helper-attendance')
@login_required
def helper_attendance():
    year   = request.args.get('year',  ph_today().year,  type=int)
    month  = request.args.get('month', ph_today().month, type=int)
    years  = list(range(2024, ph_today().year + 2))

    last_day = calendar.monthrange(year, month)[1]
    mo_s     = date(year, month, 1)
    mo_e     = date(year, month, last_day)
    days     = list(range(1, last_day + 1))

    helpers = Helper.query.filter_by(active=True).order_by(Helper.name).all()

    records = (HelperAttendance.query
               .filter(HelperAttendance.date >= mo_s, HelperAttendance.date <= mo_e)
               .all())
    att_map = {}
    for r in records:
        att_map[(r.helper_id, r.date.day)] = r.status

    summary = {}
    for hlp in helpers:
        summary[hlp.id] = {s: 0 for s in ATTENDANCE_STATUSES}
        for day in days:
            st = att_map.get((hlp.id, day))
            if st and st in summary[hlp.id]:
                summary[hlp.id][st] += 1

    return render_template('attendance/helper_index.html',
        year=year, month=month, years=years,
        mo_s=mo_s, days=days,
        helpers=helpers, att_map=att_map, summary=summary,
        att_statuses=ATTENDANCE_STATUSES)


@app.route('/api/helper-attendance/set', methods=['POST'])
@login_required
def api_helper_attendance_set():
    data      = request.get_json()
    helper_id = data.get('helper_id')
    date_str  = data.get('date')
    status    = data.get('status')

    if not helper_id or not date_str:
        return jsonify({'error': 'Missing fields'}), 400

    d = parse_date(date_str)
    record = HelperAttendance.query.filter_by(helper_id=helper_id, date=d).first()

    if status is None or status == '':
        if record:
            db.session.delete(record)
            db.session.commit()
        return jsonify({'status': '', 'date': date_str, 'helper_id': helper_id})

    if not record:
        record = HelperAttendance(helper_id=helper_id, date=d)
        db.session.add(record)

    record.status     = status
    record.updated_by = get_user()
    record.updated_at = datetime.utcnow()
    db.session.commit()

    hlp = Helper.query.get(helper_id)
    log_change(f"Helper Attendance {hlp.name if hlp else helper_id}: {status} on {d}", 'attendance')
    db.session.commit()

    return jsonify({'status': status, 'date': date_str, 'helper_id': helper_id})


# ── BREAKDOWN ──────────────────────────────────────────────────────────────
@app.route('/breakdown')
@login_required
def breakdown():
    year   = request.args.get('year',  ph_today().year,  type=int)
    month  = request.args.get('month', ph_today().month, type=int)
    filter_status = request.args.get('status', 'all')
    years  = list(range(2024, ph_today().year + 2))

    last_day = calendar.monthrange(year, month)[1]
    mo_s     = date(year, month, 1)
    mo_e     = date(year, month, last_day)

    q = BreakdownLog.query.filter(
        BreakdownLog.date >= mo_s,
        BreakdownLog.date <= mo_e
    )
    if filter_status != 'all':
        q = q.filter(BreakdownLog.status == filter_status)

    logs = q.order_by(BreakdownLog.date.desc(), BreakdownLog.id.desc()).all()

    plates      = Plate.query.filter_by(active=True).order_by(Plate.plate_no).all()
    truck_types = TruckTypeDef.query.order_by(TruckTypeDef.sort_order).all()

    # Summary counts
    all_logs_month = BreakdownLog.query.filter(
        BreakdownLog.date >= mo_s,
        BreakdownLog.date <= mo_e
    ).all()
    summary = {s: sum(1 for l in all_logs_month if l.status == s) for s in BREAKDOWN_STATUSES}
    summary['Total'] = len(all_logs_month)

    return render_template('breakdown/index.html',
        year=year, month=month, years=years, mo_s=mo_s,
        logs=logs, plates=plates, truck_types=truck_types,
        filter_status=filter_status,
        bd_statuses=BREAKDOWN_STATUSES, summary=summary)


def _parse_dt(s):
    """Accept 'YYYY-MM-DDTHH:MM' (HTML5 datetime-local) or 'YYYY-MM-DD HH:MM[:SS]'."""
    if not s:
        return None
    s = str(s).strip()
    for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%d %H:%M',  '%Y-%m-%d %H:%M:%S'):
        try:    return datetime.strptime(s, fmt)
        except: continue
    return None

@app.route('/api/breakdown/add', methods=['POST'])
def api_breakdown_add():
    data = request.get_json()
    plate_id    = data.get('plate_id') or None
    date_str    = data.get('date', ph_today().isoformat())
    description = (data.get('description') or '').strip()
    status      = data.get('status', 'Under Repair')
    remarks     = (data.get('remarks') or '').strip()
    started_at  = _parse_dt(data.get('started_at'))
    ended_at    = _parse_dt(data.get('ended_at'))

    if plate_id: plate_id = int(plate_id)

    log = BreakdownLog(
        plate_id    = plate_id,
        date        = parse_date(date_str),
        description = description or None,
        status      = status,
        remarks     = remarks or None,
        started_at  = started_at,
        ended_at    = ended_at,
        updated_by  = get_user(),
    )
    db.session.add(log)
    db.session.commit()

    plate = Plate.query.get(plate_id) if plate_id else None
    log_change(f"Breakdown logged: {plate.display if plate else 'Unknown'} on {date_str} — {status}", 'breakdown')
    db.session.commit()

    return jsonify(log.to_dict())


@app.route('/api/breakdown/<int:lid>/update', methods=['POST'])
def api_breakdown_update(lid):
    data = request.get_json()
    log  = BreakdownLog.query.get_or_404(lid)

    if 'plate_id' in data:
        log.plate_id = int(data['plate_id']) if data['plate_id'] else None
    if 'date' in data:
        log.date = parse_date(data['date'])
    if 'description' in data:
        log.description = data['description'] or None
    if 'status' in data:
        log.status = data['status']
    if 'resolved_date' in data:
        rd = data['resolved_date']
        log.resolved_date = parse_date(rd) if rd else None
    if 'started_at' in data:
        log.started_at = _parse_dt(data['started_at'])
    if 'ended_at' in data:
        log.ended_at = _parse_dt(data['ended_at'])
    if 'remarks' in data:
        log.remarks = data['remarks'] or None

    log.updated_by = get_user()
    log.updated_at = datetime.utcnow()
    db.session.commit()

    log_change(f"Updated breakdown #{lid}", 'breakdown')
    db.session.commit()

    return jsonify(log.to_dict())


@app.route('/api/breakdown/<int:lid>/delete', methods=['POST'])
def api_breakdown_delete(lid):
    if not check_can_delete():
        return jsonify({'error': 'You do not have permission to delete.'}), 403
    log = BreakdownLog.query.get_or_404(lid)
    info = f"breakdown #{lid}"
    db.session.delete(log)
    log_change(f"Deleted {info}", 'breakdown')
    db.session.commit()
    return jsonify({'ok': True})


# ── CARTRACK GPS INTEGRATION ──────────────────────────────────────────────
@app.route('/api/cartrack/vehicles')
@login_required
def api_cartrack_vehicles():
    """Return the list of vehicles from Cartrack (for plate-mapping UI)."""
    from cartrack_client import CartrackClient
    cc = CartrackClient.from_env()
    if not cc.configured:
        return jsonify({'error': 'Cartrack not configured. Set CARTRACK_USERNAME and CARTRACK_PASSWORD in environment variables.'}), 503
    vehicles, err = cc.list_vehicles()
    if err:
        return jsonify({'error': err}), 502
    # Trim down to just what the UI needs
    slim = [{
        'vehicle_id':    v.get('vehicle_id'),
        'registration':  v.get('registration') or v.get('vehicle_name'),
        'vehicle_name':  v.get('vehicle_name'),
        'description':   v.get('client_vehicle_description'),
        'type':          v.get('vehicle_type'),
    } for v in (vehicles or [])]
    return jsonify({'vehicles': slim, 'total': len(slim)})


@app.route('/api/cartrack/plate/<int:plate_id>/map', methods=['POST'])
@login_required
def api_cartrack_plate_map(plate_id):
    """Map a Plate to a Cartrack vehicle_id (or clear the mapping)."""
    plate = Plate.query.get_or_404(plate_id)
    data = request.get_json() or {}
    cartrack_id = data.get('cartrack_vehicle_id')
    if cartrack_id in (None, '', 0):
        plate.cartrack_vehicle_id = None
        action = f"Unmapped {plate.display} from Cartrack"
    else:
        try:
            plate.cartrack_vehicle_id = int(cartrack_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid cartrack_vehicle_id'}), 400
        action = f"Mapped {plate.display} -> Cartrack #{cartrack_id}"
    db.session.commit()
    log_change(action, 'plates')
    db.session.commit()
    return jsonify({'ok': True, 'plate_id': plate.id,
                    'cartrack_vehicle_id': plate.cartrack_vehicle_id})


@app.route('/api/cartrack/auto-map', methods=['POST'])
@login_required
def api_cartrack_auto_map():
    """Try to auto-match all unmapped active plates to Cartrack vehicles by
    matching the plate number against the vehicle's registration field."""
    from cartrack_client import CartrackClient
    cc = CartrackClient.from_env()
    if not cc.configured:
        return jsonify({'error': 'Cartrack not configured'}), 503

    vehicles, err = cc.list_vehicles()
    if err:
        return jsonify({'error': err}), 502

    matched, ambiguous, unmatched = [], [], []
    plates = Plate.query.filter(Plate.active == True,
                                Plate.cartrack_vehicle_id.is_(None)).all()
    from cartrack_client import _norm_plate
    for plate in plates:
        target = _norm_plate(plate.plate_no)
        if not target:
            continue
        hits = []
        for v in vehicles:
            for field in ('registration', 'vehicle_name'):
                v_norm = _norm_plate(v.get(field) or '')
                if target and v_norm and target in v_norm:
                    hits.append(v)
                    break
        if len(hits) == 1:
            plate.cartrack_vehicle_id = hits[0].get('vehicle_id')
            matched.append({'plate': plate.display,
                            'cartrack_id': plate.cartrack_vehicle_id,
                            'cartrack_name': hits[0].get('vehicle_name')})
        elif len(hits) > 1:
            ambiguous.append({'plate': plate.display,
                              'candidates': [h.get('vehicle_name') for h in hits]})
        else:
            unmatched.append(plate.display)
    db.session.commit()
    log_change(f"Cartrack auto-map: {len(matched)} matched, {len(ambiguous)} ambiguous, {len(unmatched)} unmatched", 'plates')
    db.session.commit()
    return jsonify({
        'matched_count':   len(matched),
        'ambiguous_count': len(ambiguous),
        'unmatched_count': len(unmatched),
        'matched':         matched,
        'ambiguous':       ambiguous,
        'unmatched':       unmatched,
    })


@app.route('/api/cartrack/poll-now', methods=['POST'])
@login_required
def api_cartrack_poll_now():
    """Manually trigger the polling worker. Returns the summary dict."""
    try:
        from cartrack_poll import run_poll
        summary = run_poll(app=app)
        return jsonify(summary)
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


@app.route('/api/cartrack/poll-cron', methods=['GET', 'POST'])
def api_cartrack_poll_cron():
    """External-cron entrypoint for Cartrack polling.

    Bypasses @login_required so services like cron-job.org or GitHub Actions
    can hit this endpoint on a schedule. Auth is via a shared secret token
    set in the CRON_SECRET environment variable.

    Usage:
        GET/POST /api/cartrack/poll-cron?token=YOUR_SECRET
        — OR —
        GET/POST /api/cartrack/poll-cron
        Header: X-Cron-Token: YOUR_SECRET

    Returns the same summary dict as /api/cartrack/poll-now on success,
    or 401 if the token is missing/invalid, 500 on poll exceptions.
    """
    # Resolve the expected secret
    expected = os.environ.get('CRON_SECRET', '').strip()
    if not expected:
        return jsonify({
            'error': 'CRON_SECRET env var not configured on server. '
                     'Set it in the WSGI config to enable this endpoint.'
        }), 503

    # Accept token from either query string or header (cron-job.org friendly)
    provided = (request.args.get('token') or
                request.headers.get('X-Cron-Token') or '').strip()
    if not provided or provided != expected:
        return jsonify({'error': 'Unauthorized — invalid or missing token'}), 401

    # Run the same polling worker as the "Poll Now" button
    try:
        from cartrack_poll import run_poll
        summary = run_poll(app=app)
        # Augment with caller info for cron dashboard visibility
        summary['triggered_by'] = 'cron'
        summary['ts'] = ph_now().isoformat()
        return jsonify(summary)
    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'trace': traceback.format_exc(),
        }), 500


@app.route('/api/cartrack/status')
@login_required
def api_cartrack_status():
    """Diagnostic endpoint: how many plates are mapped, when last poll ran, etc."""
    total_plates = Plate.query.filter_by(active=True).count()
    mapped_plates = Plate.query.filter(
        Plate.active == True, Plate.cartrack_vehicle_id.isnot(None)
    ).count()
    # Most recent CartrackEvent
    last_event = CartrackEvent.query.order_by(CartrackEvent.created_at.desc()).first()
    # CartrackTruckState count + open trips count
    state_total = CartrackTruckState.query.count()
    open_trips  = CartrackTruckState.query.filter(
        CartrackTruckState.entry_plaza.isnot(None)
    ).count()
    # Cartrack config
    cartrack_configured = bool(os.environ.get('CARTRACK_USERNAME') and
                               os.environ.get('CARTRACK_PASSWORD'))
    # Toll fills today
    from sqlalchemy import func
    today = ph_today()
    fills_today = (db.session.query(func.count(CartrackEvent.id))
                   .filter(CartrackEvent.event_type == 'trip_closed',
                           CartrackEvent.toll_fee.isnot(None),
                           func.date(CartrackEvent.created_at) == today)
                   .scalar() or 0)
    return jsonify({
        'cartrack_configured': cartrack_configured,
        'plates_total':        total_plates,
        'plates_mapped':       mapped_plates,
        'plates_unmapped':     total_plates - mapped_plates,
        'tracked_trucks':      state_total,
        'open_trips':          open_trips,
        'last_event': {
            'when':       last_event.created_at.isoformat() if last_event else None,
            'plate_id':   last_event.plate_id if last_event else None,
            'type':       last_event.event_type if last_event else None,
            'plaza':      last_event.plaza_name if last_event else None,
        } if last_event else None,
        'auto_fills_today': fills_today,
    })


# ── TOLL CALCULATOR ───────────────────────────────────────────────────────
import json as _json_mod
from collections import deque
_TOLL_DATA = None

def get_toll_data():
    global _TOLL_DATA
    if _TOLL_DATA is None:
        try:
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'toll_rates.json')
            # Force UTF-8 — file contains special chars like ñ (Parañaque, etc.)
            # Default encoding on some Linux locales is ASCII, which would fail.
            with open(p, 'r', encoding='utf-8') as f:
                _TOLL_DATA = _json_mod.load(f)
        except Exception as e:
            import sys
            err = f'[Toll] Could not load toll_rates.json: {e}'
            print(err, flush=True)
            sys.stderr.write(err + '\n')
            sys.stderr.flush()
            _TOLL_DATA = {}
    return _TOLL_DATA

# Expressway connection points — where two expressways physically meet.
# Each pair is bidirectional: (expA, stationA) <-> (expB, stationB)
_TOLL_CONNECTIONS = [
    # NLEX south end ↔ Skyway Stage 3 north end (Balintawak) — free transfer, same physical point
    (('NLEX_SCTEX', 'Balintawak'),        ('Skyway_Stage3', 'Balintawak')),
    (('NLEX_SCTEX', 'Mindanao Avenue'),   ('Skyway_Stage3', 'Balintawak')),
    # Skyway Stage 3 south end ↔ Skyway / SLEX north end (Buendia) — free transfer
    (('Skyway_Stage3', 'Buendia'),        ('Skyway_SLEX_MCX', 'Skyway / Buendia')),
    # Skyway/SLEX south end ↔ STAR north end (Sto. Tomas / Calamba)
    (('Skyway_SLEX_MCX', 'Sto. Tomas'),   ('STAR', 'Sto. Tomas')),
    (('Skyway_SLEX_MCX', 'Calamba'),      ('STAR', 'Calamba')),
    # NLEX/SCTEX north end ↔ TPLEX south end
    (('NLEX_SCTEX', 'Tarlac'),            ('TPLEX', 'La Paz')),
    # NLEX/SCTEX terminus alias — Sta. Ines ≈ Mabalacat area
    (('NLEX_SCTEX', 'Sta. Ines'),         ('NLEX_SCTEX', 'Mabalacat')),
    # Skyway/SLEX ↔ CALAX
    (('Skyway_SLEX_MCX', 'Mamplasan'),    ('CALAX', 'Laguna Boulevard')),
    # Skyway ↔ NAIAX (Skyway entry from NAIAX side maps to Skyway/Buendia area)
    (('Skyway_SLEX_MCX', 'Skyway / Buendia'), ('NAIAX', 'Skyway')),
    (('Skyway_SLEX_MCX', 'Magallanes'),       ('NAIAX', 'Skyway')),
    # NAIAX south end ↔ CAVITEX (the two systems meet near the airport-Cavite corridor)
    (('NAIAX', 'CAVITEX'),                ('CAVITEX', 'Parañaque')),
    (('NAIAX', 'CAVITEX'),                ('CAVITEX', 'C5 Rd. Ext./C.P. Garcia')),

    # NLEX Connector — 8-km elevated bypass linking NLEX (Caloocan side) to
    # Skyway Stage 3 (España side) without going through EDSA.
    # North end: C-3 Road / 5th Ave., same physical area as NLEX Balintawak/Karuhatan.
    (('NLEX_Connector', 'C-3 Road/5th Ave.'), ('NLEX_SCTEX', 'Balintawak')),
    (('NLEX_Connector', 'C-3 Road/5th Ave.'), ('NLEX_SCTEX', 'Karuhatan')),
    # South end: España area, drops onto Skyway Stage 3 near Quirino / Plaza Dilao.
    (('NLEX_Connector', 'España'),             ('Skyway_Stage3', 'Quirino')),
    (('NLEX_Connector', 'España'),             ('Skyway_Stage3', 'Plaza Dilao')),

    # Harbor Link / NLEX Segment 10 — spur of NLEX heading to Manila Port.
    # Karuhatan booth is the same physical location on both NLEX and Harbor Link.
    (('Harbor_Link', 'Karuhatan/Valenzuela'), ('NLEX_SCTEX', 'Karuhatan')),
    # Harbor Link Interchange = the NLEX junction (already-free transfer point).
    (('Harbor_Link', 'Harbor Link Interchange'), ('NLEX_SCTEX', 'Balintawak')),
    # Harbor Link and NLEX Connector share a C-3 Road exit (same physical booth).
    (('Harbor_Link', 'C-3 Road/5th Ave.'), ('NLEX_Connector', 'C-3 Road/5th Ave.')),
]

def _toll_lookup(matrix, a, b):
    """Symmetric rate lookup in a class matrix."""
    return matrix.get(a, {}).get(b) or matrix.get(b, {}).get(a)

def find_toll_route(entry, exit_point, toll_class, data):
    """
    BFS across expressway connection points to find the cheapest multi-hop route.
    Returns (total_amount, segments_list) or (None, None).
    segments_list = [{'expressway': key, 'from': stn, 'to': stn, 'amount': float}, ...]
    """
    # Build bidirectional neighbour map for connection stations
    conn_neighbours = {}   # (exp, stn) -> [(exp, stn), ...]
    for (e1, s1), (e2, s2) in _TOLL_CONNECTIONS:
        conn_neighbours.setdefault((e1, s1), []).append((e2, s2))
        conn_neighbours.setdefault((e2, s2), []).append((e1, s1))

    # BFS state: (exp_key, station, accumulated_cost, segments)
    # Seed with every expressway that contains the entry station
    queue = deque()
    for exp_key, exp_data in data.items():
        matrix = exp_data.get(toll_class, {})
        if entry in matrix or any(entry in v for v in matrix.values()):
            queue.append((exp_key, entry, 0.0, []))

    visited   = set()
    best_cost = None
    best_segs = None

    while queue:
        cur_exp, cur_stn, cost_so_far, segs = queue.popleft()

        state = (cur_exp, cur_stn)
        if state in visited:
            continue
        visited.add(state)

        matrix = data.get(cur_exp, {}).get(toll_class, {})

        # ── Can we reach the exit from current expressway? ──────────────────
        amt = _toll_lookup(matrix, cur_stn, exit_point)
        if amt is not None:
            total = cost_so_far + amt
            if best_cost is None or total < best_cost:
                best_cost = total
                best_segs = segs + [{'expressway': cur_exp,
                                      'from': cur_stn, 'to': exit_point,
                                      'amount': amt}]
            continue   # don't expand further — already reached destination

        # ── Try every connection point reachable from current expressway ────
        for (c_exp, c_stn), neighbours in conn_neighbours.items():
            if c_exp != cur_exp:
                continue
            conn_amt = _toll_lookup(matrix, cur_stn, c_stn) if cur_stn != c_stn else 0.0
            if conn_amt is None:
                continue
            new_segs = segs + [{'expressway': cur_exp,
                                 'from': cur_stn, 'to': c_stn,
                                 'amount': conn_amt}]
            for next_exp, next_stn in neighbours:
                if (next_exp, next_stn) not in visited:
                    queue.append((next_exp, next_stn,
                                  cost_so_far + conn_amt, new_segs))

    return best_cost, best_segs

@app.route('/api/toll/expressways')
def api_toll_expressways():
    data = get_toll_data()
    result = [{'key': k, 'name': v.get('name', k)} for k, v in data.items()]
    return jsonify(result)

@app.route('/api/toll/all-stations')
def api_toll_all_stations():
    """Return every station across all expressways with which expressway(s) it belongs to."""
    data = get_toll_data()
    station_map = {}   # station_name -> set of expressway keys
    for exp_key, exp_data in data.items():
        matrix = exp_data.get('Class 3', exp_data.get('Class 1', exp_data.get('Class 2', {})))
        for stn in matrix.keys():
            station_map.setdefault(stn, set()).add(exp_key)
    result = [
        {'station': s, 'expressways': sorted(exps)}
        for s, exps in sorted(station_map.items())
    ]
    return jsonify(result)

@app.route('/api/toll/stations/<expressway>')
def api_toll_stations(expressway):
    data = get_toll_data()
    exp = data.get(expressway, {})
    matrix = exp.get('Class 3', exp.get('Class 1', exp.get('Class 2', {})))
    stations = sorted(matrix.keys())
    return jsonify(stations)

@app.route('/api/toll/calculate', methods=['POST'])
def api_toll_calculate():
    req = request.get_json()
    expressway  = req.get('expressway', '')   # optional – auto-detected if blank
    entry       = req.get('entry', '')
    exit_point  = req.get('exit', '')
    toll_class  = req.get('toll_class', 'Class 3')
    data = get_toll_data()

    # Auto-detect expressway: try every expressway until a rate is found
    if not expressway:
        for exp_key, exp_data in data.items():
            matrix = exp_data.get(toll_class, {})
            amt = (matrix.get(entry, {}).get(exit_point) or
                   matrix.get(exit_point, {}).get(entry))
            if amt is not None:
                expressway = exp_key
                break

    exp = data.get(expressway, {})
    matrix = exp.get(toll_class, {})
    amount = (matrix.get(entry, {}).get(exit_point) or
              matrix.get(exit_point, {}).get(entry))
    if amount is None:
        # ── Fallback: BFS multi-expressway routing ──────────────────────────
        best_cost, best_segs = find_toll_route(entry, exit_point, toll_class, data)
        if best_cost is not None:
            return jsonify({'amount': best_cost, 'segments': best_segs,
                            'expressway': 'multi', 'entry': entry,
                            'exit': exit_point, 'toll_class': toll_class})
        return jsonify({'error': 'Rate not found', 'amount': 0})
    return jsonify({'amount': amount, 'expressway': expressway,
                    'segments': [{'expressway': expressway, 'from': entry,
                                  'to': exit_point, 'amount': amount}],
                    'entry': entry, 'exit': exit_point, 'toll_class': toll_class})

@app.route('/toll-calculator')
@login_required
def toll_calculator():
    return render_template('toll_calculator.html')


# ── TOLL LOG (Cartrack GPS Events) ────────────────────────────────────────
@app.route('/toll-log')
@login_required
def toll_log():
    """Render the Toll Log page — shows all Cartrack plaza events and auto-fills."""
    return render_template('toll_log/index.html')


@app.route('/api/toll-log/summary')
@login_required
def api_toll_log_summary():
    """Return summary stats for the Toll Log page: today/week/month counts + fees."""
    today = ph_today()
    today_start = datetime.combine(today, datetime.min.time())
    week_start  = today_start - timedelta(days=7)
    month_start = today_start - timedelta(days=30)

    def stats_for(since):
        events = CartrackEvent.query.filter(CartrackEvent.created_at >= since)
        total = events.count()
        enters = events.filter_by(event_type='enter').count()
        exits  = events.filter_by(event_type='exit').count()
        closed = events.filter_by(event_type='trip_closed').all()
        total_fee = sum((e.toll_fee or 0) for e in closed)
        unique_trucks = events.with_entities(CartrackEvent.plate_id).distinct().count()
        return {
            'total_events': total,
            'enters': enters,
            'exits': exits,
            'trip_closed': len(closed),
            'total_toll_fee': round(total_fee, 2),
            'unique_trucks': unique_trucks,
        }

    return jsonify({
        'today': stats_for(today_start),
        'week':  stats_for(week_start),
        'month': stats_for(month_start),
    })


@app.route('/api/toll-log/events')
@login_required
def api_toll_log_events():
    """Return filtered list of CartrackEvent rows for the Toll Log table."""
    # Parse filters
    date_from = request.args.get('date_from', '')
    date_to   = request.args.get('date_to', '')
    plate_id  = request.args.get('plate_id', '')
    event_type= request.args.get('event_type', '')
    expressway= request.args.get('expressway', '')
    limit     = int(request.args.get('limit', 200))

    q = CartrackEvent.query
    if date_from:
        try:
            d = datetime.strptime(date_from, '%Y-%m-%d')
            q = q.filter(CartrackEvent.created_at >= d)
        except ValueError:
            pass
    if date_to:
        try:
            d = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            q = q.filter(CartrackEvent.created_at < d)
        except ValueError:
            pass
    if plate_id:
        try:
            q = q.filter(CartrackEvent.plate_id == int(plate_id))
        except ValueError:
            pass
    if event_type:
        q = q.filter(CartrackEvent.event_type == event_type)
    if expressway:
        q = q.filter(CartrackEvent.expressway == expressway)

    events = q.order_by(CartrackEvent.created_at.desc()).limit(limit).all()

    rows = []
    for e in events:
        plate = e.plate
        rows.append({
            'id':         e.id,
            'created_at': e.created_at.isoformat() if e.created_at else None,
            'plate_id':   e.plate_id,
            # Display form ("DT06 / LAK8098") so the UI doesn't need the
            # truck code memorized — falls back to bare plate_no if
            # body_no isn't set.
            'plate_no':   plate.display if plate else 'N/A',
            'event_type': e.event_type,
            'plaza_name': e.plaza_name or '',
            'expressway': e.expressway or '',
            'lat':        e.lat,
            'lng':        e.lng,
            'trip_id':    e.trip_id,
            'toll_fee':   e.toll_fee,
            'toll_entry': e.toll_entry,
            'toll_exit':  e.toll_exit,
            'notes':      e.notes or '',
        })
    return jsonify({'events': rows, 'count': len(rows), 'limit': limit})


@app.route('/api/toll-log/filters')
@login_required
def api_toll_log_filters():
    """Return dropdown options for filters: plates with events, expressways."""
    # Plates that have at least one event
    plate_ids = [pid for (pid,) in
                 db.session.query(CartrackEvent.plate_id).distinct().all()
                 if pid is not None]
    plates = Plate.query.filter(Plate.id.in_(plate_ids))\
                        .order_by(Plate.plate_no).all() if plate_ids else []

    # Distinct expressways
    expressways = sorted(set(
        (e or '') for (e,) in
        db.session.query(CartrackEvent.expressway).distinct().all()
        if e
    ))

    return jsonify({
        'plates':      [{'id': p.id, 'plate_no': p.plate_no} for p in plates],
        'expressways': expressways,
        'event_types': ['enter', 'exit', 'trip_closed'],
    })


@app.route('/api/toll-log/export')
@login_required
def api_toll_log_export():
    """Export filtered events to Excel (.xlsx)."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError:
        return jsonify({'error': 'openpyxl not installed on server'}), 500

    # Same filters as events endpoint
    date_from = request.args.get('date_from', '')
    date_to   = request.args.get('date_to', '')
    plate_id  = request.args.get('plate_id', '')
    event_type= request.args.get('event_type', '')
    expressway= request.args.get('expressway', '')

    q = CartrackEvent.query
    if date_from:
        try:
            d = datetime.strptime(date_from, '%Y-%m-%d')
            q = q.filter(CartrackEvent.created_at >= d)
        except ValueError:
            pass
    if date_to:
        try:
            d = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            q = q.filter(CartrackEvent.created_at < d)
        except ValueError:
            pass
    if plate_id:
        try:
            q = q.filter(CartrackEvent.plate_id == int(plate_id))
        except ValueError:
            pass
    if event_type:
        q = q.filter(CartrackEvent.event_type == event_type)
    if expressway:
        q = q.filter(CartrackEvent.expressway == expressway)

    events = q.order_by(CartrackEvent.created_at.desc()).all()

    # Build workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Toll Log"

    # Header row with styling
    headers = ['Date/Time', 'Plate No', 'Event Type', 'Plaza',
               'Expressway', 'Toll Fee', 'Entry Plaza', 'Exit Plaza',
               'Trip ID', 'Lat', 'Lng', 'Notes']
    header_font = Font(bold=True, color='FFFFFF')
    header_fill = PatternFill('solid', fgColor='8B1A2B')
    center = Alignment(horizontal='center', vertical='center')

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center

    # Data rows
    for row_idx, e in enumerate(events, 2):
        plate = e.plate
        plate_no = plate.display if plate else 'N/A'
        ws.cell(row=row_idx, column=1,  value=e.created_at.strftime('%Y-%m-%d %H:%M:%S') if e.created_at else '')
        ws.cell(row=row_idx, column=2,  value=plate_no)
        ws.cell(row=row_idx, column=3,  value=e.event_type or '')
        ws.cell(row=row_idx, column=4,  value=e.plaza_name or '')
        ws.cell(row=row_idx, column=5,  value=e.expressway or '')
        ws.cell(row=row_idx, column=6,  value=float(e.toll_fee) if e.toll_fee else None)
        ws.cell(row=row_idx, column=7,  value=e.toll_entry or '')
        ws.cell(row=row_idx, column=8,  value=e.toll_exit or '')
        ws.cell(row=row_idx, column=9,  value=e.trip_id)
        ws.cell(row=row_idx, column=10, value=e.lat)
        ws.cell(row=row_idx, column=11, value=e.lng)
        ws.cell(row=row_idx, column=12, value=e.notes or '')

    # Summary row at bottom (total toll fees)
    if events:
        last_row = len(events) + 1
        summary_row = last_row + 2
        ws.cell(row=summary_row, column=1, value='TOTAL TOLL FEES:').font = Font(bold=True)
        ws.cell(row=summary_row, column=6,
                value=f'=SUM(F2:F{last_row})').font = Font(bold=True)

    # Auto-size columns
    column_widths = [20, 15, 14, 22, 12, 12, 22, 22, 10, 12, 12, 30]
    for col_idx, width in enumerate(column_widths, 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    # Freeze header row
    ws.freeze_panes = 'A2'

    # Send file
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f'toll_log_{ph_today().isoformat()}.xlsx'
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


# ── TRUCK CYCLE TIME (round-trip analytics + idling) ──────────────────────
@app.route('/truck-cycle-time')
@login_required
def truck_cycle_time():
    """Render the Truck Cycle Time analytics page."""
    return render_template('truck_cycle_time/index.html')


@app.route('/api/cycle-time/summary')
@login_required
def api_cycle_time_summary():
    """KPI summary for the Truck Cycle Time page.

    Returns counts + averages for today, last 7 days, last 30 days,
    plus a snapshot of currently-open cycles.
    """
    from sqlalchemy import func
    now = ph_now()
    today_start = datetime.combine(ph_today(), datetime.min.time())
    week_start  = today_start - timedelta(days=7)
    month_start = today_start - timedelta(days=30)

    def stats_for(since):
        cycles = TruckCycle.query.filter(
            TruckCycle.started_at >= since,
            TruckCycle.ended_at.isnot(None),
        ).all()
        closed_count = len(cycles)
        durations = [c.duration_minutes for c in cycles if c.duration_minutes]
        avg_minutes = round(sum(durations) / len(durations), 1) if durations else 0
        by_cat = {'short': 0, 'standard': 0, 'long': 0}
        for c in cycles:
            if c.category in by_cat:
                by_cat[c.category] += 1
        return {
            'closed_cycles':    closed_count,
            'avg_minutes':      avg_minutes,
            'avg_hours':        round(avg_minutes / 60, 2) if avg_minutes else 0,
            'by_category':      by_cat,
        }

    open_cycles = TruckCycle.query.filter(TruckCycle.ended_at.is_(None)).all()

    # Pre-fetch live state rows for all open cycles in one query (avoids N+1).
    plate_ids = [c.plate_id for c in open_cycles]
    state_map = {}
    if plate_ids:
        states = CartrackTruckState.query.filter(
            CartrackTruckState.plate_id.in_(plate_ids)
        ).all()
        state_map = {s.plate_id: s for s in states}

    # Pre-fetch geofence names so the "Currently at: X" badge can resolve
    # UUID -> name without one query per cycle.
    all_gf_uuids = set()
    for s in state_map.values():
        for u in (s.last_geofence_uuids or '').split(','):
            if u:
                all_gf_uuids.add(u)
    gf_name_map = {}
    if all_gf_uuids:
        for g in CartrackGeofence.query.filter(
            CartrackGeofence.cartrack_id.in_(all_gf_uuids)
        ).all():
            gf_name_map[g.cartrack_id] = g.name

    open_summary = []
    for c in open_cycles[:50]:   # cap to keep payload small
        elapsed_min = int((datetime.utcnow() - c.started_at).total_seconds() / 60)
        state = state_map.get(c.plate_id)
        # Resolve current geofence name(s) — usually just one, but the truck
        # could be in nested zones (e.g., customer site inside an industrial park).
        current_gf_names = []
        if state and state.last_geofence_uuids:
            for u in state.last_geofence_uuids.split(','):
                if u and u in gf_name_map:
                    current_gf_names.append(gf_name_map[u])
        # Compute "last seen" age in minutes so UI can flag stale data
        last_seen_age_min = None
        if state and state.last_position_at:
            last_seen_age_min = int(
                (datetime.utcnow() - state.last_position_at).total_seconds() / 60)
        open_summary.append({
            'cycle_id':    c.id,
            'plate_id':    c.plate_id,
            'plate_no':    c.plate.display if c.plate else 'N/A',
            'started_at':  c.started_at.isoformat() if c.started_at else None,
            'elapsed_minutes': elapsed_min,
            'elapsed_hours':   round(elapsed_min / 60, 1),
            # NEW: live state (from CartrackTruckState, refreshed every poll)
            'location':         (state.last_position_description if state else '') or '—',
            'current_geofences': current_gf_names,
            'status':           (state.live_status if state else 'UNKNOWN'),
            'speed':            (state.last_speed if state else 0),
            'last_seen_min_ago': last_seen_age_min,
        })

    # Expose the threshold so the UI can show "Min dwell: 5 min"
    try:
        from cartrack_poll import MIN_VISIT_MINUTES, TRACK_HOME_AS_VISIT
    except ImportError:
        MIN_VISIT_MINUTES, TRACK_HOME_AS_VISIT = 5, False

    home_row = CartrackGeofence.query.filter_by(is_home=True).first()
    return jsonify({
        'today':       stats_for(today_start),
        'week':        stats_for(week_start),
        'month':       stats_for(month_start),
        'open_count':  len(open_cycles),
        'open':        open_summary,
        'home_geofence': home_row.name if home_row else None,
        'min_visit_minutes':  MIN_VISIT_MINUTES,
        'track_home_as_visit': TRACK_HOME_AS_VISIT,
    })


@app.route('/api/cycle-time/cycles')
@login_required
def api_cycle_time_cycles():
    """Return list of cycles with filters.

    Query params:
        date_from, date_to  — ISO dates, filter by started_at
        plate_id            — single plate
        truck_type_id       — filter by truck type (DT / TH / MDT / ...)
        category            — short / standard / long / ongoing
        status              — 'open' / 'closed' / 'all'
        limit               — max rows (default 200)
    """
    date_from = request.args.get('date_from', '')
    date_to   = request.args.get('date_to', '')
    plate_id  = request.args.get('plate_id', '')
    truck_type_id = request.args.get('truck_type_id', '')
    category  = request.args.get('category', '')
    status    = request.args.get('status', 'all')
    limit     = min(int(request.args.get('limit', 200)), 1000)

    q = TruckCycle.query
    if date_from:
        try:
            q = q.filter(TruckCycle.started_at >= datetime.strptime(date_from, '%Y-%m-%d'))
        except ValueError:
            pass
    if date_to:
        try:
            q = q.filter(TruckCycle.started_at < datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
        except ValueError:
            pass
    if plate_id:
        try:
            q = q.filter(TruckCycle.plate_id == int(plate_id))
        except ValueError:
            pass
    if truck_type_id:
        try:
            # TruckCycle has no direct truck_type_id — join through Plate.
            q = q.join(Plate, TruckCycle.plate_id == Plate.id) \
                 .filter(Plate.truck_type_id == int(truck_type_id))
        except ValueError:
            pass
    if category:
        q = q.filter(TruckCycle.category == category)
    if status == 'open':
        q = q.filter(TruckCycle.ended_at.is_(None))
    elif status == 'closed':
        q = q.filter(TruckCycle.ended_at.isnot(None))

    cycles = q.order_by(TruckCycle.started_at.desc()).limit(limit).all()

    # Pre-fetch live state for OPEN cycles only — no point joining for closed
    # cycles since the truck has long since moved on.
    open_plate_ids = [c.plate_id for c in cycles if c.ended_at is None]
    state_map = {}
    gf_name_map = {}
    if open_plate_ids:
        states = CartrackTruckState.query.filter(
            CartrackTruckState.plate_id.in_(open_plate_ids)
        ).all()
        state_map = {s.plate_id: s for s in states}
        # Resolve geofence names for the "Currently at" column
        all_gf_uuids = set()
        for s in states:
            for u in (s.last_geofence_uuids or '').split(','):
                if u:
                    all_gf_uuids.add(u)
        if all_gf_uuids:
            for g in CartrackGeofence.query.filter(
                CartrackGeofence.cartrack_id.in_(all_gf_uuids)
            ).all():
                gf_name_map[g.cartrack_id] = g.name

    rows = []
    for c in cycles:
        # Count only REAL visits (exclude drive-bys) in this cycle.
        visit_count = (SiteVisit.query
                       .filter_by(cycle_id=c.id)
                       .filter(SiteVisit.is_drive_by == False)   # noqa: E712
                       .count())
        is_open = c.ended_at is None
        # Resolve live fields (only meaningful for open cycles).
        live = {'location': '', 'current_geofences': [], 'status': '', 'speed': 0}
        if is_open:
            state = state_map.get(c.plate_id)
            if state:
                live['location'] = state.last_position_description or ''
                live['status']   = state.live_status
                live['speed']    = state.last_speed or 0
                if state.last_geofence_uuids:
                    for u in state.last_geofence_uuids.split(','):
                        if u and u in gf_name_map:
                            live['current_geofences'].append(gf_name_map[u])
        rows.append({
            'id':          c.id,
            'plate_id':    c.plate_id,
            'plate_no':    c.plate.display if c.plate else 'N/A',
            'started_at':  c.started_at.isoformat() if c.started_at else None,
            'ended_at':    c.ended_at.isoformat() if c.ended_at else None,
            'duration_minutes': c.duration_minutes,
            'duration_hours':   (round(c.duration_minutes / 60, 1) if c.duration_minutes else None),
            'category':    c.category,
            'visit_count': visit_count,
            'is_open':     is_open,
            # Live state (populated only when is_open=True)
            'location':         live['location'],
            'current_geofences': live['current_geofences'],
            'status':           live['status'],
            'speed':            live['speed'],
        })
    return jsonify({'cycles': rows, 'count': len(rows), 'limit': limit})


@app.route('/api/cycle-time/idling')
@login_required
def api_cycle_time_idling():
    """Return aggregated idling stats per truck.

    Computed across the date range from SiteVisit records:
      total_visits, total_duration_minutes, total_idling_minutes,
      idling_pct (overall), avg_idling_pct_per_visit.

    Used by the idling-rate bar chart on the Truck Cycle Time page.
    """
    date_from = request.args.get('date_from', '')
    date_to   = request.args.get('date_to', '')
    truck_type_id = request.args.get('truck_type_id', '')

    # Build query — excludes drive-by visits by default since they're
    # transient touches, not real delivery stops. Use ?include_drive_by=1
    # to see them.
    include_drive_by = request.args.get('include_drive_by', '0') in ('1', 'true', 'True')

    from sqlalchemy import func
    q = (db.session.query(
            SiteVisit.plate_id,
            func.count(SiteVisit.id).label('visits'),
            func.coalesce(func.sum(SiteVisit.duration_seconds), 0).label('total_dur'),
            func.coalesce(func.sum(SiteVisit.idling_seconds), 0).label('total_idle'),
            func.avg(SiteVisit.idling_pct).label('avg_pct'),
         )
         .filter(SiteVisit.exit_at.isnot(None))   # only closed visits
         .group_by(SiteVisit.plate_id))
    if not include_drive_by:
        q = q.filter(SiteVisit.is_drive_by == False)   # noqa: E712

    if date_from:
        try:
            q = q.filter(SiteVisit.enter_at >= datetime.strptime(date_from, '%Y-%m-%d'))
        except ValueError:
            pass
    if date_to:
        try:
            q = q.filter(SiteVisit.enter_at < datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
        except ValueError:
            pass
    if truck_type_id:
        try:
            q = q.join(Plate, SiteVisit.plate_id == Plate.id) \
                 .filter(Plate.truck_type_id == int(truck_type_id))
        except ValueError:
            pass

    results = q.all()
    plate_map = {p.id: p for p in Plate.query.all()}

    rows = []
    for r in results:
        plate = plate_map.get(r.plate_id)
        total_dur = int(r.total_dur or 0)
        total_idle = int(r.total_idle or 0)
        pct_overall = round(100.0 * total_idle / total_dur, 1) if total_dur else 0
        rows.append({
            'plate_id':         r.plate_id,
            'plate_no':         plate.display if plate else 'N/A',
            'visits':           int(r.visits or 0),
            'total_minutes':    round(total_dur / 60, 1),
            'idling_minutes':   round(total_idle / 60, 1),
            'idling_pct':       pct_overall,
            'avg_idling_pct':   round(r.avg_pct or 0, 1),
        })
    # Sort by idling % desc
    rows.sort(key=lambda x: x['idling_pct'], reverse=True)
    return jsonify({'rows': rows, 'count': len(rows)})


@app.route('/api/cycle-time/filters')
@login_required
def api_cycle_time_filters():
    """Dropdown options: plates with cycle data, truck types, cycle categories."""
    plate_ids = [pid for (pid,) in
                 db.session.query(TruckCycle.plate_id).distinct().all()
                 if pid is not None]
    plates = (Plate.query.filter(Plate.id.in_(plate_ids))
                       .order_by(Plate.body_no, Plate.plate_no).all() if plate_ids else [])
    # Only surface truck types that actually have plates with cycle history —
    # avoids cluttering the dropdown with empty options.
    truck_type_ids = {p.truck_type_id for p in plates if p.truck_type_id}
    truck_types = (TruckTypeDef.query.filter(TruckTypeDef.id.in_(truck_type_ids))
                                    .order_by(TruckTypeDef.sort_order,
                                              TruckTypeDef.code).all()
                   if truck_type_ids else [])
    return jsonify({
        'plates': [{'id': p.id,
                    'plate_no': p.display,
                    'truck_type_id': p.truck_type_id}
                   for p in plates],
        'truck_types': [{'id': t.id, 'code': t.code, 'name': t.name,
                         'color': t.color} for t in truck_types],
        'categories': ['short', 'standard', 'long', 'ongoing'],
    })


@app.route('/api/cycle-time/export')
@login_required
def api_cycle_time_export():
    """Export cycles to Excel."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError:
        return jsonify({'error': 'openpyxl not installed'}), 500

    date_from = request.args.get('date_from', '')
    date_to   = request.args.get('date_to', '')
    plate_id  = request.args.get('plate_id', '')
    truck_type_id = request.args.get('truck_type_id', '')
    category  = request.args.get('category', '')

    q = TruckCycle.query
    if date_from:
        try:
            q = q.filter(TruckCycle.started_at >= datetime.strptime(date_from, '%Y-%m-%d'))
        except ValueError:
            pass
    if date_to:
        try:
            q = q.filter(TruckCycle.started_at < datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
        except ValueError:
            pass
    if plate_id:
        try:
            q = q.filter(TruckCycle.plate_id == int(plate_id))
        except ValueError:
            pass
    if truck_type_id:
        try:
            q = q.join(Plate, TruckCycle.plate_id == Plate.id) \
                 .filter(Plate.truck_type_id == int(truck_type_id))
        except ValueError:
            pass
    if category:
        q = q.filter(TruckCycle.category == category)

    cycles = q.order_by(TruckCycle.started_at.desc()).all()

    wb = Workbook()
    ws = wb.active
    ws.title = 'Truck Cycles'

    headers = ['Started', 'Ended', 'Plate', 'Duration (hrs)', 'Category',
               'Visit Count', 'Total Idling (min)', 'Status']
    hf = Font(bold=True, color='FFFFFF')
    hfill = PatternFill('solid', fgColor='8B1A2B')
    ca = Alignment(horizontal='center', vertical='center')
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.font = hf; cell.fill = hfill; cell.alignment = ca

    for row_idx, c in enumerate(cycles, 2):
        plate = c.plate
        ws.cell(row=row_idx, column=1, value=c.started_at.strftime('%Y-%m-%d %H:%M') if c.started_at else '')
        ws.cell(row=row_idx, column=2, value=c.ended_at.strftime('%Y-%m-%d %H:%M') if c.ended_at else '')
        ws.cell(row=row_idx, column=3, value=plate.display if plate else 'N/A')
        ws.cell(row=row_idx, column=4, value=round(c.duration_minutes / 60, 2) if c.duration_minutes else None)
        ws.cell(row=row_idx, column=5, value=c.category)
        ws.cell(row=row_idx, column=6, value=SiteVisit.query.filter_by(cycle_id=c.id).count())
        ws.cell(row=row_idx, column=7, value=c.total_idling_minutes)
        ws.cell(row=row_idx, column=8, value='Open' if c.ended_at is None else 'Closed')

    column_widths = [18, 18, 14, 14, 12, 12, 18, 10]
    for col_idx, w in enumerate(column_widths, 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = w
    ws.freeze_panes = 'A2'

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'truck_cycles_{ph_today().isoformat()}.xlsx'
    )


@app.route('/api/cycle-time/sync-geofences', methods=['POST'])
@login_required
def api_cycle_time_sync_geofences():
    """Admin trigger: pull all geofences from Cartrack into local cache.

    Should be called once after setup, then periodically (e.g., weekly)
    to pick up new geofences admins create in Cartrack. The polling
    worker only reads from the local cache, so newly-created geofences
    in Cartrack won't be tracked until this sync runs.
    """
    try:
        from cartrack_poll import sync_geofences
        summary = sync_geofences(app=app)
        return jsonify(summary)
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ── GOOGLE SHEETS SYNC ────────────────────────────────────────────────────
@app.route('/api/sync-to-sheets', methods=['POST'])
@login_required
def api_sync_to_sheets():
    import urllib.request, json as _json

    webhook_url = AppSetting.get(SHEETS_WEBHOOK_KEY, SHEETS_WEBHOOK_DEFAULT)
    if not webhook_url:
        return jsonify({'error': 'Google Sheets webhook URL not configured.'}), 400

    # ── Build payload ──────────────────────────────────────────────────────
    # TRIPS
    trip_headers = ['Date','Truck Type','Wave','Trip #','Driver','Helper',
                    'Plate','Product','Client','Dispatcher','Trip Type',
                    'RS No','PO No','Reference','DR No','Volume','Status','Notes']
    trips_rows = []
    for w in Wave.query.order_by(Wave.date.desc()).all():
        for t in w.trips:
            trips_rows.append([
                w.date.isoformat(),
                w.truck_type.name if w.truck_type else '',
                w.label,
                t.trip_number,
                t.driver.name     if t.driver     else '',
                t.helper.name     if t.helper     else '',
                t.plate.display   if t.plate      else '',
                t.product.name    if t.product    else '',
                t.client.name     if t.client     else '',
                t.dispatcher.name if t.dispatcher else '',
                t.trip_type or '',
                t.rs_no or '', t.po_no or '', t.reference or '',
                t.dr_no or '', t.volume or '',
                t.status or '', t.notes or '',
            ])

    # ATTENDANCE
    att_headers = ['Driver','Date','Status','Remarks']
    att_rows = []
    for a in Attendance.query.order_by(Attendance.date.desc()).all():
        att_rows.append([
            a.driver.name if a.driver else '',
            a.date.isoformat(),
            a.status or '',
            a.remarks or '',
        ])

    # BREAKDOWN
    bd_headers = ['Plate','Date','Description','Status','Resolved Date','Remarks']
    bd_rows = []
    for b in BreakdownLog.query.order_by(BreakdownLog.date.desc()).all():
        bd_rows.append([
            b.plate.display if b.plate else '',
            b.date.isoformat(),
            b.description or '',
            b.status or '',
            b.resolved_date.isoformat() if b.resolved_date else '',
            b.remarks or '',
        ])

    # DRIVERS
    drv_headers = ['Name','Active']
    drv_rows = [[d.name, 'Yes' if d.active else 'No']
                for d in Driver.query.order_by(Driver.name).all()]

    # PLATES
    plt_headers = ['Plate No','Body No','Truck Type','Active']
    plt_rows = [[p.plate_no, p.body_no or '',
                 p.truck_type.name if p.truck_type else '',
                 'Yes' if p.active else 'No']
                for p in Plate.query.order_by(Plate.plate_no).all()]

    payload = {
        'action': 'sync_all',
        'trips':      {'headers': trip_headers, 'rows': trips_rows},
        'attendance': {'headers': att_headers,  'rows': att_rows},
        'breakdown':  {'headers': bd_headers,   'rows': bd_rows},
        'drivers':    {'headers': drv_headers,  'rows': drv_rows},
        'plates':     {'headers': plt_headers,  'rows': plt_rows},
    }

    # ── POST to Google Apps Script ─────────────────────────────────────────
    try:
        body = _json.dumps(payload).encode('utf-8')
        req  = urllib.request.Request(
            webhook_url,
            data=body,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read().decode('utf-8'))

        if result.get('ok'):
            # Save last sync timestamp
            AppSetting.set('last_sheets_sync', ph_now().strftime('%b %d, %Y %I:%M %p'))
            db.session.commit()
            log_change('Synced data to Google Sheets', 'backup')
            db.session.commit()
            return jsonify({'ok': True,
                            'synced': {
                                'trips': len(trips_rows),
                                'attendance': len(att_rows),
                                'breakdown': len(bd_rows),
                                'drivers': len(drv_rows),
                                'plates': len(plt_rows),
                            }})
        else:
            return jsonify({'error': result.get('error', 'Unknown error from Google Sheets')}), 500

    except Exception as ex:
        return jsonify({'error': str(ex)}), 500


@app.route('/api/restore-from-sheets', methods=['POST'])
@login_required
def api_restore_from_sheets():
    import urllib.request, json as _json
    from auth.routes import check_can_delete

    # Admin only
    if session.get('user_role') != 'admin':
        return jsonify({'error': 'Admin access required.'}), 403

    webhook_url = AppSetting.get(SHEETS_WEBHOOK_KEY, SHEETS_WEBHOOK_DEFAULT)
    if not webhook_url:
        return jsonify({'error': 'Webhook URL not configured.'}), 400

    # Fetch data from Google Sheets via Apps Script doGet
    try:
        get_url = webhook_url + '?action=export'
        req = urllib.request.Request(get_url, method='GET')
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode('utf-8')
            data = _json.loads(raw)
    except Exception as ex:
        return jsonify({'error': f'Could not fetch from Google Sheets: {str(ex)}'}), 500

    if not data.get('ok'):
        return jsonify({'error': data.get('error', 'Unknown error from Google Sheets')}), 500

    restored = {'trips': 0, 'drivers': 0, 'plates': 0, 'attendance': 0, 'breakdown': 0}

    try:
        # ── Restore Drivers ───────────────────────────────────────────────
        for row in data.get('drivers', []):
            name = (row.get('Name') or '').strip()
            if not name: continue
            if not Driver.query.filter_by(name=name).first():
                db.session.add(Driver(name=name, active=True))
                restored['drivers'] += 1
        db.session.commit()

        # ── Restore Plates ────────────────────────────────────────────────
        for row in data.get('plates', []):
            plate_no = (row.get('Plate No') or '').strip()
            if not plate_no: continue
            if not Plate.query.filter_by(plate_no=plate_no).first():
                db.session.add(Plate(plate_no=plate_no,
                                     body_no=row.get('Body No') or None,
                                     active=True))
                restored['plates'] += 1
        db.session.commit()

        # ── Restore Trips ─────────────────────────────────────────────────
        for row in data.get('trips', []):
            date_str = (row.get('Date') or '').strip()
            if not date_str: continue
            try:
                d = date.fromisoformat(date_str)
            except Exception:
                continue

            truck_name = (row.get('Truck Type') or '').strip()
            tt = TruckTypeDef.query.filter_by(name=truck_name).first()
            if not tt: continue

            wave_label = (row.get('Wave') or '').strip()
            wave_num = 1
            for num, label in [(1,'1st Wave'),(2,'2nd Wave'),(3,'3rd Wave'),
                               (4,'4th Wave'),(5,'5th Wave'),(6,'6th Wave'),
                               (7,'7th Wave'),(8,'8th Wave')]:
                if label == wave_label:
                    wave_num = num; break

            wave = Wave.query.filter_by(date=d, truck_type_id=tt.id,
                                        wave_number=wave_num).first()
            if not wave:
                wave = Wave(date=d, truck_type_id=tt.id, wave_number=wave_num)
                db.session.add(wave)
                db.session.commit()

            # Use original trip number from sheet
            try:
                trip_num = int(float(str(row.get('Trip #') or 1)))
            except Exception:
                trip_num = 1

            # Skip if this trip already exists in the wave (prevent duplicates)
            if TripRecord.query.filter_by(wave_id=wave.id, trip_number=trip_num).first():
                continue

            drv  = Driver.query.filter_by(name=(row.get('Driver') or '').strip()).first()
            prod = Product.query.filter_by(name=(row.get('Product') or '').strip()).first()
            cli  = Client.query.filter_by(name=(row.get('Client') or '').strip()).first()

            # Plate display may be "body_no / plate_no" — extract plate_no
            plate_display = (row.get('Plate') or '').strip()
            plt = None
            if plate_display:
                if ' / ' in plate_display:
                    plate_no_part = plate_display.split(' / ', 1)[1].strip()
                    plt = Plate.query.filter_by(plate_no=plate_no_part).first()
                else:
                    plt = Plate.query.filter_by(plate_no=plate_display).first()

            trip = TripRecord(
                wave_id      = wave.id,
                trip_number  = trip_num,
                driver_id    = drv.id  if drv  else None,
                plate_id     = plt.id  if plt  else None,
                product_id   = prod.id if prod else None,
                client_id    = cli.id  if cli  else None,
                trip_type    = row.get('Trip Type') or None,
                rs_no        = row.get('RS No') or None,
                po_no        = row.get('PO No') or None,
                dr_no        = row.get('DR No') or None,
                volume       = row.get('Volume') or None,
                status       = row.get('Status') or 'Pending',
                notes        = row.get('Notes') or None,
            )
            db.session.add(trip)
            restored['trips'] += 1
        db.session.commit()

        log_change('Restored data from Google Sheets', 'backup')
        db.session.commit()
        return jsonify({'ok': True, 'restored': restored})

    except Exception as ex:
        db.session.rollback()
        return jsonify({'error': f'Restore failed: {str(ex)}'}), 500


@app.route('/api/sync-to-sheets/last')
def api_last_sync():
    return jsonify({'last_sync': AppSetting.get('last_sheets_sync', None)})


@app.route('/api/sync-to-sheets/webhook', methods=['POST'])
@login_required
def api_save_webhook():
    data = request.get_json() or {}
    url  = (data.get('url') or '').strip()
    if not url:
        return jsonify({'error': 'URL required'}), 400
    AppSetting.set(SHEETS_WEBHOOK_KEY, url)
    db.session.commit()
    return jsonify({'ok': True})


# ── COLLAB API ─────────────────────────────────────────────────────────────
@app.route('/api/settings/save', methods=['POST'])
def api_settings_save():
    data = request.get_json() or {}
    for key in DOC_HEADER_DEFAULTS:
        if key in data:
            AppSetting.set(key, data[key].strip())
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/search')
def api_search():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify({'results': []})
    like = f'%{q}%'
    results = []

    for d in Driver.query.filter(Driver.name.ilike(like), Driver.active == True).limit(6).all():
        results.append({'type': 'Driver', 'label': d.name, 'sub': '', 'url': None})

    for p in Plate.query.filter(
        db.or_(Plate.plate_no.ilike(like), Plate.body_no.ilike(like)),
        Plate.active == True
    ).limit(6).all():
        results.append({'type': 'Plate', 'label': p.display, 'sub': p.truck_type.name if p.truck_type else '', 'url': None})

    for c in Client.query.filter(Client.name.ilike(like), Client.active == True).limit(4).all():
        results.append({'type': 'Client', 'label': c.name, 'sub': '', 'url': None})

    for pr in Product.query.filter(Product.name.ilike(like), Product.active == True).limit(4).all():
        results.append({'type': 'Product', 'label': pr.name, 'sub': '', 'url': None})

    for tr in (TripRecord.query
               .filter(db.or_(
                   TripRecord.rs_no.ilike(like),
                   TripRecord.po_no.ilike(like),
                   TripRecord.dr_no.ilike(like),
                   TripRecord.reference.ilike(like),
               ))
               .join(Wave)
               .order_by(Wave.date.desc())
               .limit(6).all()):
        date_str = tr.wave.date.isoformat() if tr.wave else ''
        parts = [x for x in [tr.rs_no, tr.po_no, tr.dr_no] if x]
        results.append({
            'type': 'Trip',
            'label': ' / '.join(parts) or f'Trip #{tr.id}',
            'sub': date_str,
            'url': f'/schedule/{date_str}' if date_str else None,
        })

    return jsonify({'results': results, 'query': q})


@app.route('/api/activity')
def api_activity():
    since_ts = request.args.get('since', 0, type=float)
    since_dt = datetime.fromtimestamp(since_ts) if since_ts else None

    logs = (ChangeLog.query.order_by(ChangeLog.timestamp.desc()).limit(12).all())
    new_count = 0
    if since_dt:
        new_count = ChangeLog.query.filter(ChangeLog.timestamp > since_dt).count()

    latest_ts = logs[0].timestamp.timestamp() if logs else 0
    return jsonify({
        'latest_ts': latest_ts,
        'new_count': new_count,
        'logs': [{
            'user':   l.user_name,
            'action': l.action,
            'time':   l.timestamp.replace(tzinfo=timezone.utc).astimezone(PH_TZ).strftime('%b %d, %I:%M %p'),
            'ts':     l.timestamp.timestamp(),
        } for l in logs]
    })


@app.route('/api/set-user', methods=['POST'])
def api_set_user():
    name = (request.get_json() or {}).get('name', '').strip()
    if name:
        session['user_name'] = name
        return jsonify({'ok': True, 'name': name})
    return jsonify({'error': 'Name required'}), 400


# ── INIT ───────────────────────────────────────────────────────────────────
def init_db():
    with app.app_context():
        db.create_all()

        # ─────────────────────────────────────────────────────────────────────
        # SCHEMA MIGRATIONS — must run FIRST, before any ORM .query.all() calls.
        # SQLAlchemy generates SELECTs that include EVERY model column, so a
        # query against an unmigrated table will crash with "no such column".
        # All migrations are idempotent (column-existence checks).
        # ─────────────────────────────────────────────────────────────────────
        from sqlalchemy import inspect, text
        import sys
        inspector = inspect(db.engine)

        def has_table(name):
            try:
                return name in inspector.get_table_names()
            except Exception:
                return False

        def cols_of(table):
            try:
                return {c['name'] for c in inspector.get_columns(table)}
            except Exception:
                return set()

        def add_col(table, col, ddl):
            if not has_table(table):
                return
            if col in cols_of(table):
                return
            try:
                with db.engine.connect() as conn:
                    conn.execute(text(ddl))
                    conn.commit()
                msg = f"  Migrated: added {col} column to {table}"
                print(msg, flush=True)
                sys.stderr.write(msg + "\n")   # also write to error log so it's visible
                sys.stderr.flush()
            except Exception as e:
                err = f"  Migration FAILED for {table}.{col}: {e}"
                print(err, flush=True)
                sys.stderr.write(err + "\n")
                sys.stderr.flush()

        # trip_records — toll calculator + trip_type
        add_col('trip_records', 'trip_type',       'ALTER TABLE trip_records ADD COLUMN trip_type VARCHAR(30)')
        add_col('trip_records', 'toll_fee',        'ALTER TABLE trip_records ADD COLUMN toll_fee FLOAT')
        add_col('trip_records', 'toll_expressway', 'ALTER TABLE trip_records ADD COLUMN toll_expressway VARCHAR(50)')
        add_col('trip_records', 'toll_entry',      'ALTER TABLE trip_records ADD COLUMN toll_entry VARCHAR(80)')
        add_col('trip_records', 'toll_exit',       'ALTER TABLE trip_records ADD COLUMN toll_exit VARCHAR(80)')
        add_col('trip_records', 'toll_class',      'ALTER TABLE trip_records ADD COLUMN toll_class VARCHAR(10)')

        # clients — legacy toll fee column
        add_col('clients', 'toll_fee', 'ALTER TABLE clients ADD COLUMN toll_fee FLOAT DEFAULT 0')

        # truck_type_defs — fleet utilization scoring
        add_col('truck_type_defs', 'point_per_leg',       'ALTER TABLE truck_type_defs ADD COLUMN point_per_leg FLOAT DEFAULT 1.0')
        add_col('truck_type_defs', 'daily_target_points', 'ALTER TABLE truck_type_defs ADD COLUMN daily_target_points FLOAT DEFAULT 1.5')

        # products — full-day trip flag
        add_col('products', 'is_full_day_trip', 'ALTER TABLE products ADD COLUMN is_full_day_trip BOOLEAN DEFAULT 0')

        # breakdown_log — precise start/end timestamps for hours calculation
        add_col('breakdown_log', 'started_at', 'ALTER TABLE breakdown_log ADD COLUMN started_at DATETIME')
        add_col('breakdown_log', 'ended_at',   'ALTER TABLE breakdown_log ADD COLUMN ended_at DATETIME')

        # plates — Cartrack GPS provider linkage (which Cartrack vehicle this plate maps to)
        add_col('plates', 'cartrack_vehicle_id',
                'ALTER TABLE plates ADD COLUMN cartrack_vehicle_id INTEGER')

        # drivers — truck type category (which type they're trained/assigned to drive)
        # Legacy single-category column. Source of truth moved to driver_truck_types
        # association table below; this column is kept and backfilled for compat.
        add_col('drivers', 'truck_type_id', 'ALTER TABLE drivers ADD COLUMN truck_type_id INTEGER')

        # driver_truck_types — many-to-many association so a driver can be qualified
        # for multiple truck types. Created by db.create_all() above; here we
        # backfill it from the legacy Driver.truck_type_id column on first run.
        if has_table('driver_truck_types') and has_table('drivers'):
            existing_pairs = set()
            try:
                with db.engine.connect() as conn:
                    rows = conn.execute(text(
                        'SELECT driver_id, truck_type_id FROM driver_truck_types'
                    )).fetchall()
                    existing_pairs = {(r[0], r[1]) for r in rows}
            except Exception:
                pass
            try:
                with db.engine.connect() as conn:
                    legacy = conn.execute(text(
                        'SELECT id, truck_type_id FROM drivers '
                        'WHERE truck_type_id IS NOT NULL'
                    )).fetchall()
                    inserted = 0
                    for drv_id, tt_id in legacy:
                        if (drv_id, tt_id) in existing_pairs:
                            continue
                        try:
                            conn.execute(text(
                                'INSERT INTO driver_truck_types (driver_id, truck_type_id) '
                                'VALUES (:d, :t)'
                            ), {'d': drv_id, 't': tt_id})
                            inserted += 1
                        except Exception:
                            pass
                    if inserted:
                        conn.commit()
                        msg = f"  Migrated: backfilled {inserted} driver-to-truck-type associations"
                        print(msg, flush=True)
                        sys.stderr.write(msg + "\n")
                        sys.stderr.flush()
            except Exception as e:
                err = f"  Migration FAILED for driver_truck_types backfill: {e}"
                print(err, flush=True)
                sys.stderr.write(err + "\n")
                sys.stderr.flush()

        # ─────────────────────────────────────────────────────────────────────
        # ORM-based seeding/backfill — safe now that schema is up to date.
        # ─────────────────────────────────────────────────────────────────────
        # Add any missing truck types (works for fresh AND existing databases)
        existing_codes = {t.code for t in TruckTypeDef.query.all()}
        added = []
        for t in TRUCK_TYPES_SEED:
            if t['code'] not in existing_codes:
                db.session.add(TruckTypeDef(**t))
                added.append(t['code'])
        if added:
            db.session.commit()
            print(f"  Truck types added: {', '.join(added)}")
        # Seed default document header settings
        for key, val in DOC_HEADER_DEFAULTS.items():
            if not AppSetting.query.filter_by(key=key).first():
                db.session.add(AppSetting(key=key, value=val))
        # Seed Google Sheets webhook URL
        if not AppSetting.query.filter_by(key=SHEETS_WEBHOOK_KEY).first():
            db.session.add(AppSetting(key=SHEETS_WEBHOOK_KEY, value=SHEETS_WEBHOOK_DEFAULT))
        db.session.commit()

        # Backfill defaults for existing truck types based on code (10W gets 0.5/4.0)
        for tt in TruckTypeDef.query.all():
            seed = next((s for s in TRUCK_TYPES_SEED if s['code'] == tt.code), None)
            if seed:
                if tt.point_per_leg is None or (tt.point_per_leg == 1.0 and tt.code == '10W'):
                    tt.point_per_leg = seed['point_per_leg']
                if tt.daily_target_points is None or (tt.daily_target_points == 1.5 and tt.code == '10W'):
                    tt.daily_target_points = seed['daily_target_points']
        # Auto-flag known full-day products (case-insensitive name match)
        for prod_name in FULL_DAY_PRODUCTS_SEED:
            prod = Product.query.filter(db.func.upper(Product.name) == prod_name.upper()).first()
            if prod and not prod.is_full_day_trip:
                prod.is_full_day_trip = True
        db.session.commit()
        # Migrate: add can_delete column to users if missing
        from auth.models import User
        try:
            ucols = [c['name'] for c in inspector.get_columns('users')]
            if 'can_delete' not in ucols:
                with db.engine.connect() as conn:
                    conn.execute(text('ALTER TABLE users ADD COLUMN can_delete BOOLEAN DEFAULT 0'))
                    conn.commit()
                print("  Migrated: added can_delete column to users")
        except Exception:
            pass  # users table may not exist yet on first run

        # Migrate: add is_drive_by column to site_visits if missing.
        # site_visits was first introduced without this column (commit 3052dbf);
        # is_drive_by was added in 644c005. db.create_all() doesn't ALTER
        # existing tables, so this guarded ALTER is needed for the polling
        # worker to query SiteVisit successfully on accounts that picked up
        # the first version of the table.
        try:
            if 'site_visits' in inspector.get_table_names():
                svcols = [c['name'] for c in inspector.get_columns('site_visits')]
                if 'is_drive_by' not in svcols:
                    with db.engine.connect() as conn:
                        conn.execute(text(
                            'ALTER TABLE site_visits ADD COLUMN is_drive_by BOOLEAN DEFAULT 0'
                        ))
                        conn.commit()
                    print("  Migrated: added is_drive_by column to site_visits")
        except Exception as _mig_err:
            print(f"  Migration warning (site_visits.is_drive_by): {_mig_err}")

        # Migrate: add live-status columns to cartrack_truck_state.
        # These power the "where is each truck right now" view on the
        # Truck Cycle Time page. Older databases will have cartrack_truck_state
        # without these columns and the polling worker will crash on update.
        try:
            if 'cartrack_truck_state' in inspector.get_table_names():
                ctscols = [c['name'] for c in inspector.get_columns('cartrack_truck_state')]
                migrations = [
                    ('last_position_description', 'VARCHAR(300)'),
                    ('last_idling',               'BOOLEAN DEFAULT 0'),
                    ('last_ignition',             'BOOLEAN DEFAULT 0'),
                    ('last_speed',                'INTEGER DEFAULT 0'),
                    ('last_geofence_uuids',       'TEXT DEFAULT \'\''),
                ]
                added = []
                for col_name, col_type in migrations:
                    if col_name not in ctscols:
                        with db.engine.connect() as conn:
                            conn.execute(text(
                                f'ALTER TABLE cartrack_truck_state ADD COLUMN {col_name} {col_type}'
                            ))
                            conn.commit()
                        added.append(col_name)
                if added:
                    print(f"  Migrated: added {len(added)} columns to cartrack_truck_state: {', '.join(added)}")
        except Exception as _mig_err:
            print(f"  Migration warning (cartrack_truck_state live fields): {_mig_err}")
        # Import DeleteRequest so db.create_all() picks it up
        from auth.models import DeleteRequest  # noqa: F401
        db.create_all()  # create delete_requests table if new
        # Create default admin account if none exists
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', full_name='Administrator', role='admin')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("  Default admin created — username: admin  password: admin123")


# Initialize DB at module level so gunicorn (cloud) can start the app correctly
init_db()


if __name__ == '__main__':
    local_ip = get_local_ip()
    print(f"\n  ╔══════════════════════════════════════════╗")
    print(f"  ║   DISPATCH SCHEDULER is running          ║")
    print(f"  ║   Local  : http://localhost:5001         ║")
    print(f"  ║   Network: http://{local_ip}:5001        ║")
    print(f"  ║   Share the Network URL with your team   ║")
    print(f"  ╚══════════════════════════════════════════╝\n")
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)
