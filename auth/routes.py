from functools import wraps
from datetime import datetime
from flask import render_template, request, redirect, url_for, session, flash, jsonify
from models_v2 import db
from .models import User
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
