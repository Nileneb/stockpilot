from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Organization(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:140]
        super().save(*args, **kwargs)


class Membership(models.Model):
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
