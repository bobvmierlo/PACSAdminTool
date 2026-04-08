"""Register all route blueprints with the Flask app."""

from web.routes.auth_routes import bp as auth_bp
from web.routes.config_routes import bp as config_bp
from web.routes.dicom_routes import bp as dicom_bp
from web.routes.dicomize_routes import bp as dicomize_bp
from web.routes.hl7_routes import bp as hl7_bp
from web.routes.locale_routes import bp as locale_bp
from web.routes.logs_routes import bp as logs_bp
from web.routes.scp_routes import bp as scp_bp
from web.routes.system import bp as system_bp


def register_all(app):
    """Register every blueprint with the given Flask app instance."""
    app.register_blueprint(system_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(logs_bp)
    app.register_blueprint(locale_bp)
    app.register_blueprint(dicom_bp)
    app.register_blueprint(dicomize_bp)
    app.register_blueprint(scp_bp)
    app.register_blueprint(hl7_bp)
