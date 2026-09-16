"""
config.py — loads server settings from the .env file. This is
DIFFERENT from a user's Ventura credentials — those are entered by each
user at login time and stored (encrypted) per-session, not here.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    encryption_key: str
    cookie_secure: bool = False
    session_cookie_name: str = "screener_session"

    # A Ventura app_key used ONLY for shared, no-login-required calls
    # like the daily instruments pull — NOT tied to any individual
    # user's login. Any valid app_key works for this endpoint per the
    # docs, so this can be yours or a dedicated one you register.
    ventura_service_app_key: str

    # A full Ventura SERVICE login (separate from ventura_service_app_key
    # above, which only covers the no-auth instruments endpoint). The
    # live market data WebSocket needs a real logged-in client_id +
    # auth_token — used to power the SHARED live tick engine that all
    # users' screener views read from. This is NOT any individual
    # friend's personal login (their own logins are only used for
    # placing their own orders, handled separately in routers/auth.py).
    ventura_service_app_secret: str
    ventura_service_client_id: str
    ventura_service_pin: str
    ventura_service_totp_secret: str

    # Angel One is used ONLY as a shared historical-data source (not
    # for trading — that's all through Ventura, per-user). One set of
    # credentials here, used by the historical data puller job.
    angel_client_code: str
    angel_mpin: str
    angel_api_key: str
    angel_totp_secret: str

    # Set to "false" while iterating on API/UI code with --reload, so
    # every restart doesn't reconnect to Ventura and resubscribe to
    # all ~2,655 stocks. Set to "true" for real runs during market
    # hours. Defaults to true so production doesn't silently run
    # without the engine if this is forgotten in .env.
    auto_start_live_engine: bool = True

    # Comma-separated list of origins allowed to call this API from a
    # browser (CORS). MUST match exactly what's in your browser's
    # address bar when viewing the frontend — e.g. if you access the
    # dev server at http://<your-ec2-ip>:5173, that exact origin needs
    # to be listed here, not just "localhost", or the browser will
    # silently block every request (this caused a real "stuck on
    # Loading..." bug when only localhost was allowed).
    allowed_origins: str = "http://localhost:5173"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    class Config:
        env_file = ".env"


settings = Settings()
