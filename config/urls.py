from django.contrib import admin
from django.urls import path

from plant.views import health, home

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", home, name="home"),
    path("healthz", health, name="health"),
]
