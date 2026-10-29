from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),     # system administrator
    path("", include("workflow.urls")),  # everything else
]
