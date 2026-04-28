from django.conf import settings
from django.db import models
from django.utils.text import slugify
from django_tenants.models import DomainMixin, TenantMixin


class Organization(TenantMixin):
    """A tenant. Each Organization gets its own Postgres schema.

    `schema_name` (inherited from TenantMixin) is the Postgres schema for this
    tenant's data (catalog, inventory, vision, forecast, orders). The shared
    public schema holds Organization, Domain, Membership, User, and admin
    metadata.
    """

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Auto-create the schema on Organization.save()
    auto_create_schema = True
    # Drop the schema when the Organization is deleted
    auto_drop_schema = True

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:140]
        if not self.schema_name:
            self.schema_name = self.slug.replace("-", "_")
        super().save(*args, **kwargs)


class Domain(DomainMixin):
    """A hostname routed to a specific tenant.

    e.g. `acme.localhost` → schema "acme". The django-tenants
    TenantMainMiddleware looks up this table by `request.get_host()`.
    """

    pass


class Membership(models.Model):
    """Permission to access a given Organization (tenant subdomain).

    Lives in the public schema so that one User can be member of many tenants.
    Enforced at request time by `MembershipAccessMiddleware`.
    """

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        MANAGER = "manager", "Manager"
        STAFF = "staff", "Staff"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.STAFF)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "organization"),
                name="unique_membership_per_user_org",
            )
        ]
        ordering = ("organization__name", "user__username")

    def __str__(self) -> str:
        return f"{self.user} @ {self.organization} ({self.role})"
