from django.urls import path

from . import views

app_name = "training"

urlpatterns = [
    path("", views.dataset_list, name="dataset_list"),
    path("dataset/new/", views.dataset_new, name="dataset_new"),
    path("dataset/<int:dataset_id>/", views.dataset_detail, name="dataset_detail"),
    path("image/<int:image_id>/", views.image_annotate, name="image_annotate"),
    path(
        "image/<int:image_id>/annotations/",
        views.image_annotations,
        name="image_annotations",
    ),
    path(
        "image/<int:image_id>/suggestions/",
        views.image_suggestions,
        name="image_suggestions",
    ),
    path("jobs/", views.job_list, name="job_list"),
    path("models/", views.model_list, name="model_list"),
    path("models/<int:model_id>/activate/", views.model_activate, name="model_activate"),
]
