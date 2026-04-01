import os, io, socket, calendar
from datetime import date, datetime, timedelta
from flask import (Flask, render_template, request, redirect, url_for,
                   jsonify, session, flash, send_file)
from models_v2 import (db, TruckTypeDef, Wave, TripRecord,
                       Driver, Helper, Product, Client, Dispatcher, Plate,
                       ChangeLog, Attendance, BreakdownLog,
                       TRUCK_TYPES_SEED, STATUSES,
                       ATTENDANCE_STATUSES, BREAKDOWN_STATUSES, TRIP_TYPES)
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


# ── HELPERS ────────────────────────────────────────────────────────────────
def parse_date(s):
    try:    return date.fromisoformat(s)
    except: return date.today()

def get_user():
    return session.get('user_name', 'Dispatcher')

def log_change(action, entity='trip'):
    db.session.add(ChangeLog(user_name=get_user(), action=action, entity=entity))

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
    return dict(
        now=datetime.now(),
        today=date.today(),
        timedelta=timedelta,
        statuses=STATUSES,
        current_user=get_user(),
        local_ip=get_local_ip(),
    )


# ── INDEX ──────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return redirect(url_for('schedule', date_str=date.today().isoformat()))


# ── SCHEDULE ───────────────────────────────────────────────────────────────
@app.route('/schedule/<date_str>')
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

    return render_template('schedule/daily.html',
        d=d, schedule_map=schedule_map, counts=counts,
        trip_types=TRIP_TYPES,
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
        'trip_type': ('trip_type', str),
        'rs_no':     ('rs_no',     str),
        'po_no':     ('po_no',     str),
        'reference': ('reference', str),
        'dr_no':     ('dr_no',     str),
        'volume':    ('volume',    str),
        'status':    ('status',    str),
        'notes':     ('notes',     str),
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
    trip = TripRecord.query.get_or_404(tid)
    wave = trip.wave
    info = f"trip #{trip.trip_number} in {wave.label} ({wave.truck_type.name}) on {wave.date}"
    db.session.delete(trip)
    log_change(f"Deleted {info}", 'trip')
    db.session.commit()
    return jsonify({'ok': True})


# ── DASHBOARD ──────────────────────────────────────────────────────────────
@app.route('/dashboard')
def dashboard():
    from collections import defaultdict
    filter_date  = request.args.get('date',  date.today().isoformat())
    filter_truck = request.args.get('truck', 'all')
    filter_status= request.args.get('status','all')
    trend_end_str   = request.args.get('trend_end',   date.today().isoformat())
    trend_start_str = request.args.get('trend_start', (date.today() - timedelta(days=13)).isoformat())
    trend_end_d     = parse_date(trend_end_str)
    trend_start_d   = parse_date(trend_start_str)
    if trend_start_d > trend_end_d:
        trend_start_d, trend_end_d = trend_end_d, trend_start_d
    d = parse_date(filter_date)

    truck_types = TruckTypeDef.query.order_by(TruckTypeDef.sort_order).all()

    # Base query for the selected date
    q = (db.session.query(TripRecord)
         .join(Wave)
         .filter(Wave.date == d))
    if filter_truck != 'all':
        tt = TruckTypeDef.query.filter_by(code=filter_truck).first()
        if tt:
            q = q.filter(Wave.truck_type_id == tt.id)
    if filter_status != 'all':
        q = q.filter(TripRecord.status == filter_status)

    trips = q.all()

    # Stats
    total       = len(trips)
    by_status   = {s: sum(1 for t in trips if t.status == s) for s in STATUSES}
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
        total=total, by_status=by_status, by_truck=by_truck,
        trend_days=trend_days, trend_counts=trend_counts,
        trend_by_truck=trend_by_truck,
        recent_changes=recent_changes,
        top_drivers_by_truck=top_drivers_by_truck,
        absent_drivers=absent_drivers)


# ── MASTER DATA ────────────────────────────────────────────────────────────
@app.route('/master')
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
    db.session.commit()
    log_change(f"Updated {category[:-1]} id={item_id}", 'master')
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/master/<category>/<int:item_id>/toggle', methods=['POST'])
def api_master_toggle(category, item_id):
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
def reports():
    year        = request.args.get('year',  date.today().year,  type=int)
    month       = request.args.get('month', date.today().month, type=int)
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
    years     = list(range(2024, date.today().year + 2))

    return render_template('reports/index.html',
        year=year, month=month, years=years,
        filter_truck=filter_truck, truck_types=truck_types,
        trips=trips, by_status=by_status, mo_s=mo_s)


@app.route('/reports/export')
def export():
    year        = request.args.get('year',  date.today().year,  type=int)
    month       = request.args.get('month', date.today().month, type=int)
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
def attendance():
    year   = request.args.get('year',  date.today().year,  type=int)
    month  = request.args.get('month', date.today().month, type=int)
    years  = list(range(2024, date.today().year + 2))

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


# ── BREAKDOWN ──────────────────────────────────────────────────────────────
@app.route('/breakdown')
def breakdown():
    year   = request.args.get('year',  date.today().year,  type=int)
    month  = request.args.get('month', date.today().month, type=int)
    filter_status = request.args.get('status', 'all')
    years  = list(range(2024, date.today().year + 2))

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
    date_str    = data.get('date', date.today().isoformat())
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
    log = BreakdownLog.query.get_or_404(lid)
    info = f"breakdown #{lid}"
    db.session.delete(log)
    log_change(f"Deleted {info}", 'breakdown')
    db.session.commit()
    return jsonify({'ok': True})


# ── COLLAB API ─────────────────────────────────────────────────────────────
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
            'time':   l.timestamp.strftime('%H:%M'),
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
        # Migrate: add trip_type column if it doesn't exist yet (for existing databases)
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        cols = [c['name'] for c in inspector.get_columns('trip_records')]
        if 'trip_type' not in cols:
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE trip_records ADD COLUMN trip_type VARCHAR(30)'))
                conn.commit()
            print("  Migrated: added trip_type column to trip_records")


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
