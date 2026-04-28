from django.urls import path

from . import views

app_name = "vision"

urlpatterns = [
    path("", views.capture, name="capture"),
    path("list/", views.photo_list, name="photo_list"),
    path("<int:photo_id>/", views.photo_detail, name="photo_detail"),
    path("<int:photo_id>/apply/", views.photo_apply, name="photo_apply"),
]
