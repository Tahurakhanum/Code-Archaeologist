import os
import socket
import threading
import webbrowser

from code_archaeologist import create_app

app = create_app()


def reachable_browser_url() -> str:
    """Find the local address reachable from the desktop browser environment."""
    connection = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP connect selects the active adapter without sending any data.
        connection.connect(("8.8.8.8", 80))
        address = connection.getsockname()[0]
    except OSError:
        address = "127.0.0.1"
    finally:
        connection.close()
    return f"http://{address}:5000"


if __name__ == "__main__":
    # Cloning a repository creates Python files inside instance/. Flask's debug
    # reloader can mistake those files for an application change and restart
    # halfway through an analysis, resetting the browser connection.
    # Bind all local interfaces so browsers using either localhost or 127.0.0.1
    # can reach the development server reliably.
    url = reachable_browser_url()
    print(f"Opening Code Archaeologist in your browser: {url}")
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    app.run(host="0.0.0.0", port=5000, debug=os.environ.get("FLASK_DEBUG") == "1", use_reloader=False)
