"""Scheduling — the appointment domain.

One engine behind every channel (staff dashboard, WhatsApp, voice, web widget):
channels call the same use cases and produce the same canonical `Appointment`.
Nothing in this package imports SQLAlchemy, FastAPI, or any provider SDK.
"""
