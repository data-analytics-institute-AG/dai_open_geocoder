from flask import Flask
from routes.geocode_routes import geocode_bp
from routes.health_routes import health_bp

def create_app():
    """Application factory."""
    app = Flask(__name__)

    # Register blueprints (routes)
    app.register_blueprint(health_bp)
    app.register_blueprint(geocode_bp)

    return app


# For Docker (Gunicorn entrypoint)
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
