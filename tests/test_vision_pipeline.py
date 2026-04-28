"""Vision pipeline tests within a tenant schema."""

from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django_tenants.test.cases import TenantTestCase
from PIL import Image

from apps.catalog.models import Product
from apps.inventory.models import Stock, StockMovement
from apps.vision.models import Detection, InventoryPhoto, ProductLabel
from apps.vision.services import apply_to_stock, run_inference


def _png_bytes(seed: int = 0) -> bytes:
    img = Image.new("RGB", (32, 32), color=(seed % 255, 0, 0))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class VisionPipelineTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Acme"
        return tenant

    @classmethod
    def setup_domain(cls, domain):
        domain.domain = "acme.test.local"
        return domain

    def setUp(self):
        from django.test.utils import override_settings
        # Force the stub backend for unit tests; the real ultralytics path is
        # exercised in test_vision_integration.py.
        self._override = override_settings(
            VISION_INFERENCE_BACKEND="apps.vision.inference.StubBackend"
        )
        self._override.enable()
        self.product = Product.objects.create(
            sku="A-1", name="Widget", reorder_point=5, reorder_quantity=10
        )
        file = SimpleUploadedFile(
            "shelf.png", _png_bytes(seed=7), content_type="image/png"
        )
        self.photo = InventoryPhoto.objects.create(image=file)

    def tearDown(self):
        self._override.disable()

    def test_run_inference_creates_detections(self):
        n = run_inference(self.photo)
        self.photo.refresh_from_db()
        self.assertGreater(n, 0)
        self.assertEqual(self.photo.status, InventoryPhoto.Status.PROCESSED)
        self.assertEqual(
            Detection.objects.filter(photo=self.photo).count(), n
        )

    def test_apply_to_stock_with_mapping(self):
        run_inference(self.photo)
        label = Detection.objects.filter(photo=self.photo).first().label
        ProductLabel.objects.create(
            label=label, product=self.product, multiplier=Decimal("2")
        )
        expected = Detection.objects.filter(photo=self.photo, label=label).count()

        report = apply_to_stock(self.photo)
        self.photo.refresh_from_db()

        self.assertEqual(self.photo.status, InventoryPhoto.Status.APPLIED)
        self.assertTrue(report[label]["matched"])
        self.assertEqual(
            Stock.objects.get(product=self.product).quantity_on_hand,
            Decimal(expected) * Decimal("2"),
        )
        self.assertEqual(
            StockMovement.objects.filter(
                product=self.product,
                kind=StockMovement.Kind.PHOTO_COUNT,
            ).count(),
            1,
        )

    def test_apply_to_stock_skips_unmapped(self):
        run_inference(self.photo)
        report = apply_to_stock(self.photo)
        for entry in report.values():
            self.assertFalse(entry["matched"])
        self.assertEqual(StockMovement.objects.count(), 0)
