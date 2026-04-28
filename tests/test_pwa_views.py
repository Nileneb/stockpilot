"""Slice 5: capture views, manifest, service worker."""

from io import BytesIO

import pytest
from django.test import Client
from django.urls import reverse
from PIL import Image

from apps.vision.models import Detection, InventoryPhoto, ProductLabel


@pytest.fixture
def png_bytes():
    img = Image.new("RGB", (32, 32), color=(0, 128, 0))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def auth_client_a(user_a):
    client = Client()
    client.force_login(user_a)
    return client


@pytest.fixture
def auth_client_b(user_b):
    client = Client()
    client.force_login(user_b)
    return client


def _upload(client, png_bytes, filename="capture.png"):
    return client.post(
        reverse("vision:capture"),
        {"image": ("dummy", BytesIO(png_bytes), "image/png")},
        format="multipart",
    )


def test_capture_get_redirects_anonymous():
    client = Client()
    response = client.get(reverse("vision:capture"))
    assert response.status_code in (301, 302)
    assert "/login" in response["Location"] or "/accounts/login" in response["Location"]


def test_capture_get_authenticated_renders_form(auth_client_a):
    response = auth_client_a.get(reverse("vision:capture"))
    assert response.status_code == 200
    assert b"Take photo" in response.content


def test_capture_post_creates_photo_and_runs_inference(
    auth_client_a, user_a, org_a, settings, png_bytes
):
    settings.VISION_INFERENCE_BACKEND = "apps.vision.inference.StubBackend"
    from django.core.files.uploadedfile import SimpleUploadedFile
    file = SimpleUploadedFile("c.png", png_bytes, content_type="image/png")
    response = auth_client_a.post(reverse("vision:capture"), {"image": file})
    assert response.status_code == 302
    photo = InventoryPhoto.all_objects.get(uploaded_by=user_a)
    assert photo.organization_id == org_a.id
    assert photo.status == InventoryPhoto.Status.PROCESSED
    assert Detection.all_objects.filter(photo=photo).exists()
    assert response["Location"] == reverse("vision:photo_detail", args=[photo.id])


def test_photo_detail_shows_match_status(
    auth_client_a, user_a, org_a, product_a, settings, png_bytes
):
    settings.VISION_INFERENCE_BACKEND = "apps.vision.inference.StubBackend"
    from django.core.files.uploadedfile import SimpleUploadedFile
    file = SimpleUploadedFile("c.png", png_bytes, content_type="image/png")
    auth_client_a.post(reverse("vision:capture"), {"image": file})
    photo = InventoryPhoto.all_objects.get(uploaded_by=user_a)
    label = Detection.all_objects.filter(photo=photo).first().label
    ProductLabel.all_objects.create(
        organization=org_a, label=label, product=product_a
    )

    response = auth_client_a.get(reverse("vision:photo_detail", args=[photo.id]))
    assert response.status_code == 200
    assert b"Apply to stock" in response.content
    assert product_a.sku.encode() in response.content


def test_photo_detail_404s_for_other_org(
    auth_client_b, user_a, org_a, settings, png_bytes
):
    """A user from org B must not be able to see an org-A photo."""
    settings.VISION_INFERENCE_BACKEND = "apps.vision.inference.StubBackend"
    from django.core.files.uploadedfile import SimpleUploadedFile
    file = SimpleUploadedFile("c.png", png_bytes, content_type="image/png")
    # Upload as user_a to org_a
    Client().force_login(user_a)
    c_a = Client()
    c_a.force_login(user_a)
    c_a.post(reverse("vision:capture"), {"image": file})
    photo = InventoryPhoto.all_objects.get(uploaded_by=user_a)

    response = auth_client_b.get(reverse("vision:photo_detail", args=[photo.id]))
    assert response.status_code == 404


def test_apply_view_changes_status(
    auth_client_a, user_a, org_a, product_a, settings, png_bytes
):
    settings.VISION_INFERENCE_BACKEND = "apps.vision.inference.StubBackend"
    from django.core.files.uploadedfile import SimpleUploadedFile
    file = SimpleUploadedFile("c.png", png_bytes, content_type="image/png")
    auth_client_a.post(reverse("vision:capture"), {"image": file})
    photo = InventoryPhoto.all_objects.get(uploaded_by=user_a)
    label = Detection.all_objects.filter(photo=photo).first().label
    ProductLabel.all_objects.create(
        organization=org_a, label=label, product=product_a
    )

    response = auth_client_a.post(reverse("vision:photo_apply", args=[photo.id]))
    assert response.status_code == 302
    photo.refresh_from_db()
    assert photo.status == InventoryPhoto.Status.APPLIED


def test_manifest_returns_json():
    client = Client()
    response = client.get("/manifest.webmanifest")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert b"Stockpilot" in response.content


def test_service_worker_returns_js():
    client = Client()
    response = client.get("/sw.js")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/javascript")
    assert b"caches.open" in response.content
