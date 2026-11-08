# Python 3.13 Runtime Managed via uv

We pin the execution runtime to Python 3.13 managed by `uv` using a project `.python-version` file.

While the host workstation ships with newer Python installations, Python 3.13 provides verified stability across all underlying Google API, MSAL, and Pydantic C-extension wheels. `uv` handles downloading, isolating, and caching Python 3.13 hermetically without requiring system-level package manager intervention.
