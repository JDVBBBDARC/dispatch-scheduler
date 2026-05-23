from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone

db = SQLAlchemy()


def utc_now():
    """Return the current UTC time as a NAIVE datetime (no tzinfo).

    Drop-in replacement for `datetime.utcnow()`, which Python 3.12+
    deprecated and which is scheduled for removal in a future version.
    The recommended modern API is `datetime.now(UTC)` — but that returns
    a tz-aware datetime, and this codebase consistently stores naive UTC
    in SQLite (column defaults, comparisons, etc. all assume naive). So
    we get the current UTC moment via the new API, then strip tzinfo to
    match the existing convention.

    Use this helper anywhere you previously wrote `datetime.utcnow()`:

        from models_v2 import utc_now

        record.updated_at = utc_now()

    The output is BYTE-IDENTICAL to the old utcnow() result. Storage,
    indexes, and joins are unaffected.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)

# ── Truck type seed data ───────────────────────────────────────────────────
# point_per_leg / daily_target_points control fleet utilization scoring.
# 10W uses the 0.5/4.0 "point" system (each delivered leg = 0.5 pts,
# 4.0 pts/day = 100% utilization). All others use whole-trip counting
# with a target of 1.5 trips/day = 100% (i.e., 3 trips per 2 days).
TRUCK_TYPES_SEED = [
    {'code': '10W',  'name': '10 Wheeler Dump Truck', 'color': '#c0392b', 'sort_order': 1, 'point_per_leg': 0.5, 'daily_target_points': 4.0},
    {'code': '12W',  'name': '12 Wheeler Dump Truck', 'color': '#8e44ad', 'sort_order': 2, 'point_per_leg': 1.0, 'daily_target_points': 1.5},
    {'code': '22WD', 'name': '22W Dump Trailer',      'color': '#2980b9', 'sort_order': 3, 'point_per_leg': 1.0, 'daily_target_points': 1.5},
    {'code': '22WB', 'name': '22W Bulk Carrier',      'color': '#27ae60', 'sort_order': 4, 'point_per_leg': 1.0, 'daily_target_points': 1.5},
    {'code': 'FB',   'name': 'Flat Bed Trailer',      'color': '#d35400', 'sort_order': 5, 'point_per_leg': 1.0, 'daily_target_points': 1.5},
    {'code': 'LB',   'name': 'Lowbed Trailer',        'color': '#16a085', 'sort_order': 6, 'point_per_leg': 1.0, 'daily_target_points': 1.5},
    {'code': 'OT',   'name': 'Others',                'color': '#7f8c8d', 'sort_order': 7, 'point_per_leg': 1.0, 'daily_target_points': 1.5},
]

# Products that are inherently full-day commitments (auto-flagged on first init).
FULL_DAY_PRODUCTS_SEED = ['ASPHALT']

# Case-insensitive substring keywords. ANY product whose name contains one of
# these strings is treated as a full-day trip (counts as the truck type's
# full daily_target_points instead of point_per_leg) — even if its
# is_full_day_trip flag wasn't manually ticked. e.g., "Asphalt Plant",
# "ASPHALT MIX", "asphalt-cold" all match the 'asphalt' keyword.
FULL_DAY_KEYWORDS = ['asphalt']

def is_product_full_day(product):
    """Return True if a product should count as a full-day trip in fleet utilization.

    Two ways a product qualifies:
      1. Its is_full_day_trip flag is set (manual override in master data).
      2. Its name contains any FULL_DAY_KEYWORDS substring (case-insensitive).
    """
    if product is None:
        return False
    if getattr(product, 'is_full_day_trip', False):
        return True
    name = (getattr(product, 'name', '') or '').lower()
    return any(kw in name for kw in FULL_DAY_KEYWORDS)

TRIP_TYPES = ['Front Load', 'Back Load', 'Side Load']

DOC_HEADER_DEFAULTS = {
    'doc_title':    'LOGISTICS DELIVERY SCHEDULE',
    'doc_form_code':'F-LG-1.2',
    'doc_revision': 'Rev.1 09/15/2025',
}

SHEETS_WEBHOOK_KEY = 'gsheets_webhook_url'
SHEETS_WEBHOOK_DEFAULT = 'https://script.google.com/macros/s/AKfycbzEdjd9Pjlln2EyJpcyN8vi_JZIKo0ugtaqTuUy7VOrsCGjnE6otll1g5sZoa0f2RbB/exec'

STATUSES = ['Pending', 'In Transit', 'Delivered', 'Canceled']

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
    # Fleet-utilization scoring (editable in master data)
    point_per_leg       = db.Column(db.Float, default=1.0)   # 0.5 for 10W, 1.0 for others
    daily_target_points = db.Column(db.Float, default=1.5)   # 4.0 for 10W, 1.5 for others

    waves  = db.relationship('Wave',  back_populates='truck_type', cascade='all, delete-orphan')
    plates = db.relationship('Plate', back_populates='truck_type')


# Association table: drivers can be qualified to drive multiple truck types
driver_truck_types = db.Table(
    'driver_truck_types',
    db.Column('driver_id',     db.Integer, db.ForeignKey('drivers.id'),         primary_key=True),
    db.Column('truck_type_id', db.Integer, db.ForeignKey('truck_type_defs.id'), primary_key=True),
)


class Driver(db.Model):
    __tablename__ = 'drivers'
    id     = db.Column(db.Integer, primary_key=True)
    name   = db.Column(db.String(80), nullable=False)
    active = db.Column(db.Boolean, default=True)
    # Legacy single-category column (kept for backward compat).
    # Source of truth is now the many-to-many `truck_types` relationship below.
    truck_type_id = db.Column(db.Integer, db.ForeignKey('truck_type_defs.id'), nullable=True)

    # Multi-category: a driver can be qualified for several truck types.
    # Used by the Driver/Truck Ratio chart per-type filter.
    truck_types = db.relationship('TruckTypeDef', secondary=driver_truck_types,
                                  lazy='selectin')
    truck_type  = db.relationship('TruckTypeDef', foreign_keys=[truck_type_id])

    trips_driven       = db.relationship('TripRecord', foreign_keys='TripRecord.driver_id', back_populates='driver')
    attendance_records = db.relationship('Attendance', back_populates='driver', cascade='all, delete-orphan')


class Helper(db.Model):
    __tablename__ = 'helpers'
    id     = db.Column(db.Integer, primary_key=True)
    name   = db.Column(db.String(80), nullable=False)
    active = db.Column(db.Boolean, default=True)

    trips_helped       = db.relationship('TripRecord', foreign_keys='TripRecord.helper_id', back_populates='helper')
    attendance_records = db.relationship('HelperAttendance', back_populates='helper', cascade='all, delete-orphan')


class Product(db.Model):
    __tablename__ = 'products'
    id     = db.Column(db.Integer, primary_key=True)
    name   = db.Column(db.String(100), nullable=False)
    active = db.Column(db.Boolean, default=True)
    # Full-day commitment flag for fleet-utilization scoring
    # When True, a delivered trip with this product counts as the truck's full
    # daily target instead of the per-leg point value (e.g., ASPHALT runs).
    is_full_day_trip = db.Column(db.Boolean, default=False, nullable=False)

    trips = db.relationship('TripRecord', foreign_keys='TripRecord.product_id', back_populates='product')


class Client(db.Model):
    __tablename__ = 'clients'
    id       = db.Column(db.Integer, primary_key=True)
    name     = db.Column(db.String(100), nullable=False)
    active   = db.Column(db.Boolean, default=True)
    toll_fee = db.Column(db.Float, default=0.0, nullable=True)

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
    # Cartrack GPS provider linkage. When set, the polling worker can fetch
    # this truck's live position and detect toll plaza crossings to
    # auto-fill toll fees on TripRecord. NULL = not yet mapped to Cartrack.
    cartrack_vehicle_id = db.Column(db.Integer, nullable=True, index=True)

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
    toll_fee      = db.Column(db.Float, nullable=True)
    toll_expressway = db.Column(db.String(50), nullable=True)
    toll_entry    = db.Column(db.String(80), nullable=True)
    toll_exit     = db.Column(db.String(80), nullable=True)
    toll_class    = db.Column(db.String(10), nullable=True)
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
            'status':           self.status or 'Pending',
            'toll_fee':         self.toll_fee or 0,
            'toll_expressway':  self.toll_expressway or '',
            'toll_entry':       self.toll_entry or '',
            'toll_exit':        self.toll_exit or '',
            'toll_class':       self.toll_class or '',
            'notes':            self.notes or '',
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


# ── Helper Attendance ──────────────────────────────────────────────────────
class HelperAttendance(db.Model):
    __tablename__ = 'helper_attendance'
    id         = db.Column(db.Integer, primary_key=True)
    helper_id  = db.Column(db.Integer, db.ForeignKey('helpers.id'), nullable=False)
    date       = db.Column(db.Date, nullable=False, index=True)
    status     = db.Column(db.String(20), default='Present')
    remarks    = db.Column(db.String(200))
    updated_by = db.Column(db.String(64))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    helper = db.relationship('Helper', back_populates='attendance_records')

    __table_args__ = (db.UniqueConstraint('helper_id', 'date', name='uq_helper_att_helper_date'),)


# ── Breakdown Log ──────────────────────────────────────────────────────────
class BreakdownLog(db.Model):
    __tablename__ = 'breakdown_log'
    id            = db.Column(db.Integer, primary_key=True)
    plate_id      = db.Column(db.Integer, db.ForeignKey('plates.id'), nullable=True)
    date          = db.Column(db.Date, nullable=False, index=True)
    description   = db.Column(db.Text)
    status        = db.Column(db.String(30), default='Under Repair')
    resolved_date = db.Column(db.Date)
    # Precise timestamps — when the unit broke down and when the repair finished.
    # Used for the "Total Breakdown Hours" KPI on the dashboard.
    started_at    = db.Column(db.DateTime, nullable=True)
    ended_at      = db.Column(db.DateTime, nullable=True)
    remarks       = db.Column(db.String(300))
    updated_by    = db.Column(db.String(64))
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    plate = db.relationship('Plate', back_populates='breakdowns')

    @property
    def duration_hours(self):
        """Hours between started_at and ended_at (0 if still ongoing)."""
        if self.started_at and self.ended_at:
            return max(0.0, (self.ended_at - self.started_at).total_seconds() / 3600.0)
        return 0.0

    def to_dict(self):
        return {
            'id':            self.id,
            'plate_id':      self.plate_id,
            'plate_display': self.plate.display if self.plate else '',
            'date':          self.date.isoformat(),
            'description':   self.description or '',
            'status':        self.status or 'Under Repair',
            'resolved_date': self.resolved_date.isoformat() if self.resolved_date else '',
            'started_at':    self.started_at.strftime('%Y-%m-%dT%H:%M') if self.started_at else '',
            'ended_at':      self.ended_at.strftime('%Y-%m-%dT%H:%M') if self.ended_at else '',
            'duration_hours': round(self.duration_hours, 2),
            'remarks':       self.remarks or '',
            'updated_by':    self.updated_by or '',
        }


# ── Cartrack GPS integration ──────────────────────────────────────────────
class CartrackTruckState(db.Model):
    """Per-plate state for the Cartrack polling worker. One row per plate.

    Tracks which toll plazas a truck is currently inside (so we can detect
    enter/exit transitions between polls), plus the running trip-tracking
    state (entry plaza, current exit candidate) used to compute toll fees.
    """
    __tablename__ = 'cartrack_truck_state'
    id              = db.Column(db.Integer, primary_key=True)
    plate_id        = db.Column(db.Integer, db.ForeignKey('plates.id'), nullable=False, unique=True, index=True)
    # Comma-separated list of plaza names the truck is currently inside.
    # e.g., "Pulilan" or "" (none). Updated every poll.
    current_plazas  = db.Column(db.Text, default='')
    # Trip-tracking state — the FIRST plaza entered in an "open" trip
    entry_plaza     = db.Column(db.String(80))
    # Latest plaza touched (becomes the exit when trip closes)
    last_plaza      = db.Column(db.String(80))
    # When we last saw plaza activity (used for the 30-min idle close rule)
    last_event_ts   = db.Column(db.DateTime)
    # Last GPS position seen (for diagnostics)
    last_lat        = db.Column(db.Float)
    last_lng        = db.Column(db.Float)
    last_position_at= db.Column(db.DateTime)
    # Live status fields — written every poll so the dispatcher UI can show
    # where a truck is and what it's doing without hitting Cartrack on every
    # page refresh. All fields refresh on every poll, even if state hasn't
    # changed (so 'last seen' age can be computed from updated_at).
    last_position_description = db.Column(db.String(300))   # "Dolores Rd, Porac, Pampanga"
    last_idling     = db.Column(db.Boolean, default=False)
    last_ignition   = db.Column(db.Boolean, default=False)
    last_speed      = db.Column(db.Integer, default=0)       # km/h
    # Comma-separated Cartrack geofence UUIDs currently inside (for the
    # "currently at SITE-X" badge in the Open Cycles list).
    last_geofence_uuids = db.Column(db.Text, default='')
    # Which TripRecord this state maps to (for auto-fill). Set when entry detected.
    open_trip_id    = db.Column(db.Integer, db.ForeignKey('trip_records.id'), nullable=True)
    # Bookkeeping
    updated_at      = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    plate = db.relationship('Plate')

    # Ad-hoc stop detection — tracks the start of an ongoing stationary
    # period so we can log it as a SiteVisit (with geofence_id=NULL)
    # when the truck eventually resumes moving. See cartrack_poll.py.
    last_stop_started_at = db.Column(db.DateTime)
    last_stop_lat        = db.Column(db.Float)
    last_stop_lng        = db.Column(db.Float)
    # Address at the start of the stop — captured from
    # cartrack get_status position_description so we don't need a
    # separate reverse-geocode step.
    last_stop_address    = db.Column(db.String(300))

    @property
    def live_status(self):
        """Computed status code from ignition/idling/speed."""
        if not self.last_ignition:
            return 'OFF'
        if self.last_speed and self.last_speed > 5:   # >5 km/h = actually moving
            return 'DRIVING'
        if self.last_idling:
            return 'IDLING'
        return 'STOPPED'


class CartrackEvent(db.Model):
    """Audit log of plaza entry/exit events detected by the polling worker.

    Used for debugging, dashboards, and post-hoc analysis.
    Auto-pruned to last 60 days to keep storage bounded.
    """
    __tablename__ = 'cartrack_events'
    id          = db.Column(db.Integer, primary_key=True)
    plate_id    = db.Column(db.Integer, db.ForeignKey('plates.id'), nullable=False, index=True)
    event_type  = db.Column(db.String(20), nullable=False)   # 'enter' | 'exit' | 'trip_closed'
    plaza_name  = db.Column(db.String(80))                   # normalized plaza name
    expressway  = db.Column(db.String(50))                   # which expressway it belongs to
    lat         = db.Column(db.Float)
    lng         = db.Column(db.Float)
    trip_id     = db.Column(db.Integer, db.ForeignKey('trip_records.id'), nullable=True)
    # For trip_closed events: the computed toll fee
    toll_fee    = db.Column(db.Float)
    toll_entry  = db.Column(db.String(80))
    toll_exit   = db.Column(db.String(80))
    # Bookkeeping
    created_at  = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    notes       = db.Column(db.String(200))

    plate = db.relationship('Plate')


# ── Cartrack Geofences (synced from Cartrack account) ─────────────────────
class CartrackGeofence(db.Model):
    """Mirrors the geofences configured in the Cartrack Fleet account.

    Synced periodically via cc.list_geofences(). The Cartrack-side UUID is
    the source of truth; we keep a local cache so the app can categorize,
    annotate, and join geofences without hitting Cartrack on every read.

    Categories are auto-assigned at sync time based on name patterns
    (e.g., 'BIG BEN SCM' -> 'home', 'SHELL ...' -> 'fuel') and can be
    edited manually later if needed.
    """
    __tablename__ = 'cartrack_geofences'

    id          = db.Column(db.Integer, primary_key=True)
    # Cartrack's stable UUID for this geofence — primary lookup key.
    cartrack_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name        = db.Column(db.String(200), nullable=False, index=True)
    description = db.Column(db.Text)
    position_description = db.Column(db.Text)   # human-readable address
    colour      = db.Column(db.String(20))      # hex from Cartrack
    # Polygon as raw WKT (POLYGON((lng lat, lng lat, ...))) — we don't run
    # geometric ops in the app (Cartrack does that via geofence_ids in
    # /rest/vehicles/status), so storage as text is fine.
    polygon_wkt = db.Column(db.Text)
    # Auto-assigned category — see _categorize_geofence() in cartrack_poll.py.
    # Values: 'home', 'customer', 'quarry', 'fuel', 'toll', 'operations', 'other'
    category    = db.Column(db.String(30), default='other', index=True)
    # True if this is a depot/home base. BIG BEN SCM should be the only one
    # marked True initially; admins can flip the flag for other depots later.
    is_home     = db.Column(db.Boolean, default=False, index=True)
    # When we last pulled this geofence from Cartrack — useful for stale
    # detection (e.g., the Cartrack-side entry was deleted but ours lingers).
    last_synced_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)


# ── Site Visits (per-truck enter/exit tracking) ───────────────────────────
class SiteVisit(db.Model):
    """One row per plate × geofence × visit (enter -> exit pair).

    Opened when the polling worker first sees a truck inside a geofence
    that it wasn't inside on the previous poll. Closed when the truck
    leaves the geofence (or after a long idle timeout).

    Idling time is accumulated across the visit — each poll where the
    truck reports idling=True AND is inside this geofence adds the
    polling interval (default 60s) to idling_seconds.
    """
    __tablename__ = 'site_visits'

    id          = db.Column(db.Integer, primary_key=True)
    plate_id    = db.Column(db.Integer, db.ForeignKey('plates.id'),
                            nullable=False, index=True)
    # NULLABLE: when NULL, this row represents an AD-HOC STOP — a place
    # where the truck stopped for >= STOP_DETECTION_MINUTES outside any
    # known geofence. address/lat/lng fields below describe the spot.
    geofence_id = db.Column(db.Integer, db.ForeignKey('cartrack_geofences.id'),
                            nullable=True, index=True)
    enter_at    = db.Column(db.DateTime, nullable=False, index=True)
    exit_at     = db.Column(db.DateTime)                       # null = ongoing
    # Cached duration (seconds). Computed when exit_at is set.
    duration_seconds = db.Column(db.Integer, default=0)
    # Cumulative idle time during this visit (seconds).
    idling_seconds = db.Column(db.Integer, default=0)
    # Idle percentage: idling / duration × 100. Computed on close.
    idling_pct  = db.Column(db.Float)
    # True if the visit was shorter than the minimum dwell threshold
    # (default 5 min) — i.e., the truck just passed through or briefly
    # touched the geofence edge. UI hides these by default since they
    # don't represent real delivery/pickup stops.
    is_drive_by = db.Column(db.Boolean, default=False, index=True)
    # Ad-hoc stop fields (populated when geofence_id IS NULL).
    # Captured from CartrackTruckState at the start of the stop.
    address  = db.Column(db.String(300))   # human-readable reverse geocode
    lat      = db.Column(db.Float)         # decimal degrees
    lng      = db.Column(db.Float)
    # Link to the TripRecord this visit belongs to, when we can match
    # by date + driver/plate (filled by a separate matcher pass).
    trip_id     = db.Column(db.Integer, db.ForeignKey('trip_records.id'),
                            nullable=True, index=True)
    # Link to the open TruckCycle this visit happened during.
    cycle_id    = db.Column(db.Integer, db.ForeignKey('truck_cycles.id'),
                            nullable=True, index=True)

    plate    = db.relationship('Plate')
    geofence = db.relationship('CartrackGeofence')

    @property
    def is_ad_hoc(self):
        """True if this row is an ad-hoc stop (no associated geofence)."""
        return self.geofence_id is None

    @property
    def location_label(self):
        """Display name for the UI: geofence name if known, address otherwise."""
        if self.geofence is not None:
            return self.geofence.name
        return self.address or '(unknown location)'


# ── Truck Cycles (home -> ... -> home round trips) ────────────────────────
class TruckCycle(db.Model):
    """One full round trip: truck leaves home -> visits sites -> returns home.

    Opened the moment a truck exits the home geofence (BIG BEN SCM).
    Closed when the same truck re-enters home. Visits made along the way
    are linked via SiteVisit.cycle_id.

    Multi-day cycles are fully supported — ended_at can be hours or days
    after started_at. While ended_at is NULL, the cycle is 'ongoing'.
    """
    __tablename__ = 'truck_cycles'

    id           = db.Column(db.Integer, primary_key=True)
    plate_id     = db.Column(db.Integer, db.ForeignKey('plates.id'),
                             nullable=False, index=True)
    started_at   = db.Column(db.DateTime, nullable=False, index=True)
    ended_at     = db.Column(db.DateTime, index=True)             # null = ongoing
    duration_minutes = db.Column(db.Integer)                       # computed on close
    # Number of distinct geofence visits during this cycle.
    visit_count  = db.Column(db.Integer, default=0)
    # Cumulative idling minutes across all visits in this cycle.
    total_idling_minutes = db.Column(db.Integer, default=0)
    # Category, auto-assigned when cycle closes:
    #   'short'    — under 12 hours (typical single-day round trip)
    #   'standard' — 12-24 hours (long single-day or quick overnight)
    #   'long'     — over 24 hours (multi-day journey)
    #   'ongoing'  — cycle still open (truck hasn't returned home)
    category     = db.Column(db.String(20), default='ongoing', index=True)

    plate = db.relationship('Plate')

    @property
    def is_open(self):
        return self.ended_at is None


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
