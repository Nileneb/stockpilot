import pytest
from django.contrib.auth import get_user_model

from apps.catalog.models import Product, Supplier
from apps.tenants.models import Membership, Organization

User = get_user_model()


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A", slug="org-a")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B", slug="org-b")


@pytest.fixture
def user_a(db, org_a):
    user = User.objects.create_user("alice", "alice@a.test", "pw")
    Membership.objects.create(user=user, organization=org_a, role=Membership.Role.OWNER)
    return user


@pytest.fixture
def user_b(db, org_b):
    user = User.objects.create_user("bob", "bob@b.test", "pw")
    Membership.objects.create(user=user, organization=org_b, role=Membership.Role.OWNER)
    return user


@pytest.fixture
def supplier_a(org_a):
    return Supplier.all_objects.create(organization=org_a, name="Supplier A")


@pytest.fixture
def supplier_b(org_b):
    return Supplier.all_objects.create(organization=org_b, name="Supplier B")


@pytest.fixture
def product_a(org_a, supplier_a):
    return Product.all_objects.create(
        organization=org_a,
        sku="A-001",
        name="Widget",
        default_supplier=supplier_a,
        reorder_point=5,
        reorder_quantity=10,
    )


@pytest.fixture
def product_b(org_b, supplier_b):
    return Product.all_objects.create(
        organization=org_b,
        sku="B-001",
        name="Gadget",
        default_supplier=supplier_b,
        reorder_point=3,
        reorder_quantity=6,
    )
