import os

import reflex as rx

config = rx.Config(
    app_name="dashboard",
    api_url=os.getenv("REFLEX_API_URL", "http://localhost:3000"),
    # Vite rejects reverse-proxy hostnames by default. Limit the exception to
    # Runloop's tunnel domain instead of allowing arbitrary Host headers.
    vite_allowed_hosts=[".tunnel.runloop.ai"],
    plugins=[
        # The theme lives here rather than on rx.App, which is deprecated.
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(appearance="inherit", accent_color="blue", radius="large")
        ),
        rx.plugins.SitemapPlugin(),
    ],
)
