"""
URL configuration for osed project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from django.http import HttpResponse
from review import views as review_views

from django.conf import settings
from django.conf.urls.static import static

# Google Search Console site verification (HTML file method). Google fetches
# this exact path and checks the body matches the file it issued.
GOOGLE_SITE_VERIFICATION = "google-site-verification: googlee57c3bde8e03885f.html\n"

urlpatterns = [
    path('', review_views.home, name='home'),
    path(
        'googlee57c3bde8e03885f.html',
        lambda request: HttpResponse(
            GOOGLE_SITE_VERIFICATION, content_type="text/html"
        ),
        name='google_site_verification',
    ),
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    path('review/', include('review.urls')),
]

if settings.DEBUG or getattr(settings, "SERVE_MEDIA", False):
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
