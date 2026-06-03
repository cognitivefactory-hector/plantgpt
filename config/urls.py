from django.contrib import admin
from django.urls import path

from plant import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.board, name="board"),
    path("seed", views.seed, name="seed"),
    path("solve", views.solve, name="solve"),
    path("ask", views.ask_page, name="ask"),
    path("ask/run", views.ask_run, name="ask_run"),
    path("propose", views.propose_page, name="propose"),
    path("propose/run", views.propose_run, name="propose_run"),
    path("propose/approve", views.propose_approve, name="propose_approve"),
    path("propose/reject", views.propose_reject, name="propose_reject"),
    path("audit", views.audit, name="audit"),
    path("healthz", views.health, name="health"),
]
