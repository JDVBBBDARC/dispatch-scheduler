from functools import wraps
from datetime import datetime
from flask import render_template, request, redirect, url_for, session, flash, jsonify
from models_v2 import db
from .models import User, DeleteRequest
from . import auth_bp


# ── Decorators ─────────────────────────────────────────────────────────────
def check_can_delete() -> bool:
    """Returns True if the current session user is allowed to delete records."""
    uid = session.get('user_id')
    if not uid:
        return False
    user = User.query.get(uid)
    # Admins can always delete; staff need can_delete flag
    return bool(user and (user.is_admin or user.can_delete))


def login_required(f):
    """Redirect to login if user is not authenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('auth.login', next=request.path))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Redirect/block if user is not an admin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('auth.login', next=request.path))
        if session.get('user_role') != 'admin':
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


# ── Login / Logout ──────────────────────────────────────────────────────────
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Already logged in → go home
    if session.get('user_id'):
        return redirect('/')

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()

        if not user or not user.is_active:
            error = 'Account not found or inactive.'
        elif not user.check_password(password):
            error = 'Incorrect password.'
        else:
            # Successful login — populate session
            session.permanent = True
            session['user_id']   = user.id
            session['user_name'] = user.display_name
            session['user_role'] = user.role
            user.last_login = datetime.utcnow()
            db.session.commit()
            next_url = request.form.get('next') or '/'
            return redirect(next_url)

    next_url = request.args.get('next', '/')
    return render_template('auth/login.html', error=error, next=next_url)


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


# ── Admin: User Management ──────────────────────────────────────────────────
@auth_bp.route('/admin/users')
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at).all()
    return render_template('auth/admin_users.html', users=users)


@auth_bp.route('/admin/users/create', methods=['POST'])
@admin_required
def admin_create_user():
    username  = request.form.get('username', '').strip()
    full_name = request.form.get('full_name', '').strip()
    password  = request.form.get('password', '')
    role      = request.form.get('role', 'staff')

    if not username or not password:
        flash('Username and password are required.', 'danger')
        return redirect(url_for('auth.admin_users'))

    if User.query.filter_by(username=username).first():
        flash(f'Username "{username}" is already taken.', 'danger')
        return redirect(url_for('auth.admin_users'))

    if len(password) < 4:
        flash('Password must be at least 4 characters.', 'danger')
        return redirect(url_for('auth.admin_users'))

    can_del = request.form.get('can_delete') == '1' and role != 'admin'
    user = User(username=username, full_name=full_name or None, role=role, can_delete=can_del)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    flash(f'Account "{username}" created successfully!', 'success')
    return redirect(url_for('auth.admin_users'))


@auth_bp.route('/admin/users/<int:uid>/toggle', methods=['POST'])
@admin_required
def admin_toggle_user(uid):
    user = User.query.get_or_404(uid)
    # Prevent admin from locking themselves out
    if user.id == session.get('user_id'):
        flash('You cannot deactivate your own account.', 'warning')
        return redirect(url_for('auth.admin_users'))
    user.is_active = not user.is_active
    db.session.commit()
    state = 'activated' if user.is_active else 'deactivated'
    flash(f'Account "{user.username}" {state}.', 'success')
    return redirect(url_for('auth.admin_users'))


@auth_bp.route('/admin/users/<int:uid>/reset', methods=['POST'])
@admin_required
def admin_reset_password(uid):
    user   = User.query.get_or_404(uid)
    new_pw = request.form.get('new_password', '')
    if len(new_pw) < 4:
        flash('New password must be at least 4 characters.', 'danger')
    else:
        user.set_password(new_pw)
        db.session.commit()
        flash(f'Password for "{user.username}" has been reset.', 'success')
    return redirect(url_for('auth.admin_users'))


@auth_bp.route('/admin/users/<int:uid>/delete', methods=['POST'])
@admin_required
def admin_delete_user(uid):
    user = User.query.get_or_404(uid)
    if user.id == session.get('user_id'):
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('auth.admin_users'))
    db.session.delete(user)
    db.session.commit()
    flash(f'Account "{user.username}" deleted.', 'warning')
    return redirect(url_for('auth.admin_users'))


# ── Delete Requests ─────────────────────────────────────────────────────────
@auth_bp.route('/api/delete-request', methods=['POST'])
def api_create_delete_request():
    """Staff submits a deletion request for admin approval."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not logged in'}), 401
    data        = request.get_json() or {}
    entity_type = data.get('entity_type', '')
    entity_id   = data.get('entity_id')
    entity_info = data.get('entity_info', '')
    reason      = data.get('reason', '').strip()

    if not entity_type or not entity_id:
        return jsonify({'error': 'Missing fields'}), 400

    req = DeleteRequest(
        requester_id = session.get('user_id'),
        entity_type  = entity_type,
        entity_id    = int(entity_id),
        entity_info  = entity_info,
        reason       = reason or None,
    )
    db.session.add(req)
    db.session.commit()
    return jsonify({'ok': True, 'request_id': req.id})


@auth_bp.route('/api/delete-requests/pending-count')
def api_pending_count():
    count = DeleteRequest.query.filter_by(status='pending').count()
    return jsonify({'count': count})


@auth_bp.route('/admin/delete-requests')
@admin_required
def admin_delete_requests():
    pending  = DeleteRequest.query.filter_by(status='pending').order_by(DeleteRequest.created_at.desc()).all()
    history  = DeleteRequest.query.filter(DeleteRequest.status != 'pending').order_by(DeleteRequest.reviewed_at.desc()).limit(30).all()
    return render_template('auth/delete_requests.html', pending=pending, history=history)


@auth_bp.route('/admin/delete-requests/<int:rid>/approve', methods=['POST'])
@admin_required
def admin_approve_delete(rid):
    from flask import current_app
    req = DeleteRequest.query.get_or_404(rid)
    if req.status != 'pending':
        flash('Request already processed.', 'warning')
        return redirect(url_for('auth.admin_delete_requests'))

    # Perform the actual deletion
    try:
        with current_app.app_context():
            _do_delete(req.entity_type, req.entity_id)
        req.status       = 'approved'
        req.reviewed_by  = session.get('user_name', 'Admin')
        req.reviewed_at  = datetime.utcnow()
        req.review_notes = request.form.get('notes', '')
        db.session.commit()
        flash(f'Request approved — "{req.entity_info}" has been deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        req.status       = 'approved'  # mark approved even if record already gone
        req.reviewed_by  = session.get('user_name', 'Admin')
        req.reviewed_at  = datetime.utcnow()
        req.review_notes = f'Auto-note: {str(e)}'
        db.session.commit()
        flash(f'Approved — record may have already been removed.', 'warning')

    return redirect(url_for('auth.admin_delete_requests'))


@auth_bp.route('/admin/delete-requests/<int:rid>/reject', methods=['POST'])
@admin_required
def admin_reject_delete(rid):
    req = DeleteRequest.query.get_or_404(rid)
    if req.status != 'pending':
        flash('Request already processed.', 'warning')
        return redirect(url_for('auth.admin_delete_requests'))
    req.status       = 'rejected'
    req.reviewed_by  = session.get('user_name', 'Admin')
    req.reviewed_at  = datetime.utcnow()
    req.review_notes = request.form.get('notes', '').strip() or None
    db.session.commit()
    flash(f'Request rejected.', 'info')
    return redirect(url_for('auth.admin_delete_requests'))


def _do_delete(entity_type: str, entity_id: int):
    """Execute the actual deletion after admin approval."""
    from models_v2 import Wave, TripRecord, BreakdownLog, Driver, Helper, Product, Client, Dispatcher, Plate
    mapping = {
        'wave':      Wave,
        'trip':      TripRecord,
        'breakdown': BreakdownLog,
        'driver':    Driver,
        'helper':    Helper,
        'product':   Product,
        'client':    Client,
        'dispatcher':Dispatcher,
        'plate':     Plate,
    }
    Model = mapping.get(entity_type)
    if not Model:
        raise ValueError(f'Unknown entity type: {entity_type}')
    obj = Model.query.get(entity_id)
    if obj:
        db.session.delete(obj)
        db.session.commit()


@auth_bp.route('/admin/users/<int:uid>/toggle-delete', methods=['POST'])
@admin_required
def admin_toggle_delete(uid):
    user = User.query.get_or_404(uid)
    if user.is_admin:
        flash('Admins always have delete permission.', 'info')
        return redirect(url_for('auth.admin_users'))
    user.can_delete = not user.can_delete
    db.session.commit()
    state = 'enabled' if user.can_delete else 'disabled'
    flash(f'Delete permission {state} for "{user.username}".', 'success')
    return redirect(url_for('auth.admin_users'))
