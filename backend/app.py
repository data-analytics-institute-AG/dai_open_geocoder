from flask import Flask
from routes.geocode_routes import geocode_bp
from routes.health_routes import health_bp
from flask_swagger_ui import get_swaggerui_blueprint

def create_app():
    """Application factory."""
    app = Flask(__name__)
    # disable JSON key sorting to preserve order
    app.json.sort_keys = False
    

    #Swagger

    SWAGGER_URL = "/swagger"
    API_URL = "/static/swagger.json"

    swaggerui_blueprint = get_swaggerui_blueprint(
        SWAGGER_URL,
        API_URL,
        config={"app_name": "Geocoding API"}
    )

    app.register_blueprint(swaggerui_blueprint, url_prefix=SWAGGER_URL)

    # Register blueprints (routes)
    app.register_blueprint(health_bp)
    app.register_blueprint(geocode_bp)

    return app


# For Docker (Gunicorn entrypoint)
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
