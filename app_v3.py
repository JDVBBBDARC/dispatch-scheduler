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
                       TRUCK_TYPES_SEED, STATUSES,
                       ATTENDANCE_STATUSES, BREAKDOWN_STATUSES, TRIP_TYPES,
                       DOC_HEADER_DEFAULTS, SHEETS_WEBHOOK_KEY, SHEETS_WEBHOOK_DEFAULT,
                       FULL_DAY_PRODUCTS_SEED)
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
    return jsonify({
        'total':          len(trips),
        'by_status':      {s: sum(1 for t in trips if t.status == s) for s in STATUSES},
        'total_toll_fee': sum((t.toll_fee or 0) for t in trips if t.status != 'Canceled'),
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

    # Build product → is_full_day map (only for products that appear in the trips)
    product_ids = {t.product_id for (t, _w) in trips if t.product_id}
    full_day_products = set()
    if product_ids:
        full_day_products = {
            pid for (pid,) in db.session.query(Product.id)
                                        .filter(Product.id.in_(product_ids),
                                                Product.is_full_day_trip == True).all()
        }

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
        clients=clients, dispatchers=dispatchers, plates=plates)


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
    db.session.add(obj)
    db.session.commit()
    log_change(f"Added {category[:-1]} '{name}'", 'master')
    db.session.commit()
    return jsonify({'id': obj.id, 'name': obj.name})


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


@app.route('/api/breakdown/add', methods=['POST'])
def api_breakdown_add():
    data = request.get_json()
    plate_id    = data.get('plate_id') or None
    date_str    = data.get('date', ph_today().isoformat())
    description = (data.get('description') or '').strip()
    status      = data.get('status', 'Under Repair')
    remarks     = (data.get('remarks') or '').strip()

    if plate_id: plate_id = int(plate_id)

    log = BreakdownLog(
        plate_id    = plate_id,
        date        = parse_date(date_str),
        description = description or None,
        status      = status,
        remarks     = remarks or None,
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


# ── TOLL CALCULATOR ───────────────────────────────────────────────────────
import json as _json_mod
from collections import deque
_TOLL_DATA = None

def get_toll_data():
    global _TOLL_DATA
    if _TOLL_DATA is None:
        try:
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'toll_rates.json')
            with open(p, 'r') as f:
                _TOLL_DATA = _json_mod.load(f)
        except Exception as e:
            print(f'[Toll] Could not load toll_rates.json: {e}')
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
    # Skyway/SLEX south end ↔ STAR north end
    (('Skyway_SLEX_MCX', 'Sto. Tomas'),  ('STAR', 'Sto. Tomas')),
    # NLEX/SCTEX north end ↔ TPLEX south end
    (('NLEX_SCTEX', 'Tarlac'),            ('TPLEX', 'La Paz')),
    # Skyway/SLEX ↔ CALAX
    (('Skyway_SLEX_MCX', 'Mamplasan'),    ('CALAX', 'Laguna Boulevard')),
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
        # Migrate: add trip_type column if it doesn't exist yet (for existing databases)
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        cols = [c['name'] for c in inspector.get_columns('trip_records')]
        if 'trip_type' not in cols:
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE trip_records ADD COLUMN trip_type VARCHAR(30)'))
                conn.commit()
            print("  Migrated: added trip_type column to trip_records")
        # Migrate: add fleet-utilization columns to truck_type_defs
        tt_cols = [c['name'] for c in inspector.get_columns('truck_type_defs')]
        if 'point_per_leg' not in tt_cols:
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE truck_type_defs ADD COLUMN point_per_leg FLOAT DEFAULT 1.0'))
                conn.commit()
            print("  Migrated: added point_per_leg column to truck_type_defs")
        if 'daily_target_points' not in tt_cols:
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE truck_type_defs ADD COLUMN daily_target_points FLOAT DEFAULT 1.5'))
                conn.commit()
            print("  Migrated: added daily_target_points column to truck_type_defs")
        # Backfill defaults for existing truck types based on code (10W gets 0.5/4.0)
        for tt in TruckTypeDef.query.all():
            seed = next((s for s in TRUCK_TYPES_SEED if s['code'] == tt.code), None)
            if seed:
                if tt.point_per_leg is None or tt.point_per_leg == 1.0 and tt.code == '10W':
                    tt.point_per_leg = seed['point_per_leg']
                if tt.daily_target_points is None or (tt.daily_target_points == 1.5 and tt.code == '10W'):
                    tt.daily_target_points = seed['daily_target_points']
        # Migrate: add is_full_day_trip column to products
        prod_cols = [c['name'] for c in inspector.get_columns('products')]
        if 'is_full_day_trip' not in prod_cols:
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE products ADD COLUMN is_full_day_trip BOOLEAN DEFAULT 0'))
                conn.commit()
            print("  Migrated: added is_full_day_trip column to products")
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
