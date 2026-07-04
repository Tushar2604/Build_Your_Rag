"""Hiring Agent — isolated persistence layer.

Reuses the platform's existing database (the shared SQLAlchemy `Base`, engine,
and async sessionmaker) but keeps its own ORM model and repository so nothing in
the core persistence package needs to change. The only schema change is one new
additive table (see migration 0005_hiring_agent_memory).
"""
