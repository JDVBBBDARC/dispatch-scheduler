from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

# ── Truck type seed data ───────────────────────────────────────────────────
TRUCK_TYPES_SEED = [
    {'code': '10W',  'name': '10 Wheeler Dump Truck', 'color': '#c0392b', 'sort_order': 1},
    {'code': '12W',  'name': '12 Wheeler Dump Truck', 'color': '#8e44ad', 'sort_order': 2},
    {'code': '22WD', 'name': '22W Dump Trailer',      'color': '#2980b9', 'sort_order': 3},
    {'code': '22WB', 'name': '22W Bulk Carrier',      'color': '#27ae60', 'sort_order': 4},
    {'code': 'FB',   'name': 'Flat Bed Trailer',      'color': '#d35400', 'sort_order': 5},
    {'code': 'LB',   'name': 'Lowbed Trailer',        'color': '#16a085', 'sort_order': 6},
    {'code': 'OT',   'name': 'Others',                'color': '#7f8c8d', 'sort_order': 7},
]

TRIP_TYPES = ['Front Load', 'Back Load', 'Side Load']

DOC_HEADER_DEFAULTS = {
    'doc_title':    'LOGISTICS DELIVERY SCHEDULE',
    'doc_form_code':'F-LG-1.2',
    'doc_revision': 'Rev.1 09/15/2025',
}

STATUSES = ['Pending', 'Loading', 'In Transit', 'Delivered']

ATTENDANCE_STATUSES = ['Present', 'Absent', 'Leave', 'Holiday']

BREAKDOWN_STATUSES = ['Under Repair', 'Fixed', 'Standby']


# ── Master data ────────────────────────────────────────────────────────────
class TruckTypeDef(db.Model):
    __tablename__ = 'truck_type_defs'
    id         = db.Column(db.Integer, primary_key=True)
    code       = db.Column(db.String(10), unique=True, nullable=False)
    name       = db.Column(db.String(60), nullable=False)
    color      = db.Column(db.String(20), default='#8B1A2B')
    sort_order = db.Column(db.Integer, default=0)

    waves  = db.relationship('Wave',  back_populates='truck_type', cascade='all, delete-orphan')
    plates = db.relationship('Plate', back_populates='truck_type')


class Driver(db.Model):
    __tablename__ = 'drivers'
    id     = db.Column(db.Integer, primary_key=True)
    name   = db.Column(db.String(80), nullable=False)
    active = db.Column(db.Boolean, default=True)

    trips_driven       = db.relationship('TripRecord', foreign_keys='TripRecord.driver_id', back_populates='driver')
    attendance_records = db.relationship('Attendance', back_populates='driver', cascade='all, delete-orphan')


class Helper(db.Model):
    __tablename__ = 'helpers'
    id     = db.Column(db.Integer, primary_key=True)
    name   = db.Column(db.String(80), nullable=False)
    active = db.Column(db.Boolean, default=True)

    trips_helped = db.relationship('TripRecord', foreign_keys='TripRecord.helper_id', back_populates='helper')


class Product(db.Model):
    __tablename__ = 'products'
    id     = db.Column(db.Integer, primary_key=True)
    name   = db.Column(db.String(100), nullable=False)
    active = db.Column(db.Boolean, default=True)

    trips = db.relationship('TripRecord', foreign_keys='TripRecord.product_id', back_populates='product')


class Client(db.Model):
    __tablename__ = 'clients'
    id     = db.Column(db.Integer, primary_key=True)
    name   = db.Column(db.String(100), nullable=False)
    active = db.Column(db.Boolean, default=True)

    trips = db.relationship('TripRecord', foreign_keys='TripRecord.client_id', back_populates='client')


class Dispatcher(db.Model):
    __tablename__ = 'dispatchers'
    id     = db.Column(db.Integer, primary_key=True)
    name   = db.Column(db.String(80), nullable=False)
    active = db.Column(db.Boolean, default=True)

    trips = db.relationship('TripRecord', foreign_keys='TripRecord.dispatcher_id', back_populates='dispatcher')


class Plate(db.Model):
    __tablename__ = 'plates'
    id            = db.Column(db.Integer, primary_key=True)
    plate_no      = db.Column(db.String(20), nullable=False)
    body_no       = db.Column(db.String(20))
    truck_type_id = db.Column(db.Integer, db.ForeignKey('truck_type_defs.id'), nullable=True)
    active        = db.Column(db.Boolean, default=True)

    truck_type  = db.relationship('TruckTypeDef', back_populates='plates')
    trips       = db.relationship('TripRecord', foreign_keys='TripRecord.plate_id', back_populates='plate')
    breakdowns  = db.relationship('BreakdownLog', back_populates='plate', cascade='all, delete-orphan')

    @property
    def display(self):
        if self.body_no:
            return f"{self.body_no} / {self.plate_no}"
        return self.plate_no


# ── Scheduling ─────────────────────────────────────────────────────────────
class Wave(db.Model):
    __tablename__ = 'waves'
    id            = db.Column(db.Integer, primary_key=True)
    date          = db.Column(db.Date, nullable=False, index=True)
    truck_type_id = db.Column(db.Integer, db.ForeignKey('truck_type_defs.id'), nullable=False)
    wave_number   = db.Column(db.Integer, default=1)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    truck_type = db.relationship('TruckTypeDef', back_populates='waves')
    trips      = db.relationship('TripRecord', back_populates='wave',
                                 cascade='all, delete-orphan',
                                 order_by='TripRecord.trip_number')

    @property
    def label(self):
        ordinals = {1:'1st',2:'2nd',3:'3rd',4:'4th',5:'5th',6:'6th',7:'7th',8:'8th'}
        return f"{ordinals.get(self.wave_number, str(self.wave_number))} Wave"


class TripRecord(db.Model):
    __tablename__ = 'trip_records'
    id            = db.Column(db.Integer, primary_key=True)
    wave_id       = db.Column(db.Integer, db.ForeignKey('waves.id'), nullable=False)
    trip_number   = db.Column(db.Integer, default=1)
    driver_id     = db.Column(db.Integer, db.ForeignKey('drivers.id'),     nullable=True)
    helper_id     = db.Column(db.Integer, db.ForeignKey('helpers.id'),     nullable=True)
    plate_id      = db.Column(db.Integer, db.ForeignKey('plates.id'),      nullable=True)
    product_id    = db.Column(db.Integer, db.ForeignKey('products.id'),    nullable=True)
    client_id     = db.Column(db.Integer, db.ForeignKey('clients.id'),     nullable=True)
    dispatcher_id = db.Column(db.Integer, db.ForeignKey('dispatchers.id'), nullable=True)
    trip_type     = db.Column(db.String(30))
    rs_no         = db.Column(db.String(50))
    po_no         = db.Column(db.String(50))
    reference     = db.Column(db.String(50))
    dr_no         = db.Column(db.String(50))
    volume        = db.Column(db.String(50))
    status        = db.Column(db.String(20), default='Pending')
    notes         = db.Column(db.Text)
    updated_by    = db.Column(db.String(64))
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    wave       = db.relationship('Wave',       back_populates='trips')
    driver     = db.relationship('Driver',     foreign_keys=[driver_id],     back_populates='trips_driven')
    helper     = db.relationship('Helper',     foreign_keys=[helper_id],     back_populates='trips_helped')
    plate      = db.relationship('Plate',      foreign_keys=[plate_id],      back_populates='trips')
    product    = db.relationship('Product',    foreign_keys=[product_id],    back_populates='trips')
    client     = db.relationship('Client',     foreign_keys=[client_id],     back_populates='trips')
    dispatcher = db.relationship('Dispatcher', foreign_keys=[dispatcher_id], back_populates='trips')

    def to_dict(self):
        return {
            'id':            self.id,
            'wave_id':       self.wave_id,
            'trip_number':   self.trip_number,
            'driver_id':     self.driver_id,
            'helper_id':     self.helper_id,
            'plate_id':      self.plate_id,
            'product_id':    self.product_id,
            'client_id':     self.client_id,
            'dispatcher_id': self.dispatcher_id,
            'trip_type':     self.trip_type or '',
            'rs_no':         self.rs_no or '',
            'po_no':         self.po_no or '',
            'reference':     self.reference or '',
            'dr_no':         self.dr_no or '',
            'volume':        self.volume or '',
            'status':        self.status or 'Pending',
            'notes':         self.notes or '',
        }


# ── Attendance ─────────────────────────────────────────────────────────────
class Attendance(db.Model):
    __tablename__ = 'attendance'
    id         = db.Column(db.Integer, primary_key=True)
    driver_id  = db.Column(db.Integer, db.ForeignKey('drivers.id'), nullable=False)
    date       = db.Column(db.Date, nullable=False, index=True)
    status     = db.Column(db.String(20), default='Present')
    remarks    = db.Column(db.String(200))
    updated_by = db.Column(db.String(64))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    driver = db.relationship('Driver', back_populates='attendance_records')

    __table_args__ = (db.UniqueConstraint('driver_id', 'date', name='uq_attendance_driver_date'),)


# ── Breakdown Log ──────────────────────────────────────────────────────────
class BreakdownLog(db.Model):
    __tablename__ = 'breakdown_log'
    id            = db.Column(db.Integer, primary_key=True)
    plate_id      = db.Column(db.Integer, db.ForeignKey('plates.id'), nullable=True)
    date          = db.Column(db.Date, nullable=False, index=True)
    description   = db.Column(db.Text)
    status        = db.Column(db.String(30), default='Under Repair')
    resolved_date = db.Column(db.Date)
    remarks       = db.Column(db.String(300))
    updated_by    = db.Column(db.String(64))
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    plate = db.relationship('Plate', back_populates='breakdowns')

    def to_dict(self):
        return {
            'id':            self.id,
            'plate_id':      self.plate_id,
            'plate_display': self.plate.display if self.plate else '',
            'date':          self.date.isoformat(),
            'description':   self.description or '',
            'status':        self.status or 'Under Repair',
            'resolved_date': self.resolved_date.isoformat() if self.resolved_date else '',
            'remarks':       self.remarks or '',
            'updated_by':    self.updated_by or '',
        }


# ── App Settings (key/value store) ────────────────────────────────────────
class AppSetting(db.Model):
    __tablename__ = 'app_settings'
    id    = db.Column(db.Integer, primary_key=True)
    key   = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.Text)

    @staticmethod
    def get(key, default=''):
        row = AppSetting.query.filter_by(key=key).first()
        return row.value if row else default

    @staticmethod
    def set(key, value):
        row = AppSetting.query.filter_by(key=key).first()
        if row:
            row.value = value
        else:
            db.session.add(AppSetting(key=key, value=value))


# ── Collaboration ──────────────────────────────────────────────────────────
class ChangeLog(db.Model):
    __tablename__ = 'change_log'
    id        = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    user_name = db.Column(db.String(64), default='Unknown')
    action    = db.Column(db.String(200))
    entity    = db.Column(db.String(30))   # trip / wave / master / attendance / breakdown
