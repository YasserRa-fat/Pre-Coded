#!/usr/bin/env python
import sys
import os
import unittest
import json
from pathlib import Path
from django.test import RequestFactory, Client
from django.urls import reverse
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.conf import settings
from django import setup as django_setup
from django.contrib.auth import get_user_model
from django.db import connection
from unittest.mock import patch

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Define BASE_DIR
BASE_DIR = Path(__file__).resolve().parent.parent

# Configure Django settings
if not settings.configured:
    settings.configure(
        INSTALLED_APPS=[
            "django.contrib.admin",
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.sessions",
            "django.contrib.messages",
            "django.contrib.staticfiles",
            "rest_framework",
            "rest_framework_simplejwt",
            "core.apps.CoreConfig",
            "create_api.apps.CreateApiConfig",
        ],
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:",
            }
        },
        REST_FRAMEWORK={
            "DEFAULT_AUTHENTICATION_CLASSES": [
                "rest_framework_simplejwt.authentication.JWTAuthentication",
            ],
            "TEST_REQUEST_RENDERER_CLASSES": [
                "rest_framework.renderers.JSONRenderer",
            ],
        },
        STATIC_URL="/static/",
        STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage",
        STATICFILES_FINDERS=[
            "django.contrib.staticfiles.finders.FileSystemFinder",
            "django.contrib.staticfiles.finders.AppDirectoriesFinder",
        ],
        STATIC_ROOT=os.path.join(BASE_DIR, "static"),
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "DIRS": [],
                "APP_DIRS": True,
                "OPTIONS": {
                    "context_processors": [
                        "django.template.context_processors.debug",
                        "django.template.context_processors.request",
                        "django.contrib.auth.context_processors.auth",
                        "django.contrib.messages.context_processors.messages",
                    ],
                },
            }
        ],
        MIDDLEWARE=[
            "django.middleware.security.SecurityMiddleware",
            "django.contrib.sessions.middleware.SessionMiddleware",
            "django.middleware.common.CommonMiddleware",
            "django.middleware.csrf.CsrfViewMiddleware",
            "django.contrib.auth.middleware.AuthenticationMiddleware",
            "django.contrib.messages.middleware.MessageMiddleware",
            "django.middleware.clickjacking.XFrameOptionsMiddleware",
        ],
        SECRET_KEY="test-secret-key",
        ALLOWED_HOSTS=["localhost", "127.0.0.1"],
        BASE_DIR=BASE_DIR,
    )
    try:
        django_setup()
        call_command("migrate", "--noinput", verbosity=0)
    except Exception as e:
        print(f"Error during Django setup or migration: {e}")
        sys.exit(1)

try:
    from create_api.models import Project, App, AIChangeRequest, TemplateFile, StaticFile
    from create_api.views import PreviewOneView
except ImportError as e:
    print(f"Error importing create_api modules: {e}")
    sys.exit(1)

from rest_framework_simplejwt.tokens import AccessToken

User = get_user_model()

class TestPreviewOneView(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Run migrations once per test class."""
        super().setUpClass()
        try:
            call_command("migrate", "--noinput", verbosity=0)
        except Exception as e:
            print(f"Error during setUpClass migration: {e}")
            raise

    def setUp(self):
        """Set up test data: user, project, apps, static files, and AIChangeRequest."""
        # Clear database to avoid UNIQUE constraint errors
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA foreign_keys = OFF")
            cursor.execute("DELETE FROM create_api_aichangerequest")
            cursor.execute("DELETE FROM create_api_staticfile")
            cursor.execute("DELETE FROM create_api_templatefile")
            cursor.execute("DELETE FROM create_api_app")
            cursor.execute("DELETE FROM create_api_project")
            cursor.execute("DELETE FROM auth_user")
            cursor.execute("PRAGMA foreign_keys = ON")

        # Use unique username per test
        username = f"testuser_{self.id()}"
        self.user = User.objects.create_user(
            username=username, password="testpass123", email=f"{username}@example.com"
        )

        # Use unique project ID based on test method name
        project_id = hash(self._testMethodName) % 10000  # Ensure unique but small ID
        self.project = Project.objects.create(id=project_id, name=f"TestProject_{project_id}", user=self.user)

        # Patch database alias and migration to avoid ConnectionDoesNotExist
        with patch("create_api.signals.call_command") as mock_call_command:
            mock_call_command.return_value = None  # Skip actual migrations
            self.posts_app = App.objects.create(project=self.project, name="posts")
            self.users_app = App.objects.create(project=self.project, name="users")

        static_css_content = """
/* TEMPLATEMO CSS */
@import url('https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css');
@import url('https://cdnjs.cloudflare.com/ajax/libs/animate.css/4.1.1/animate.min.css');
@import url('https://cdnjs.cloudflare.com/ajax/libs/aos/2.3.4/aos.css');
@import url('https://cdnjs.cloudflare.com/ajax/libs/Swiper/8.0.7/swiper-bundle.min.css');

/* OUR CSS */
body {
    font-family: 'Roboto', sans-serif;
    font-size: 16px;
    line-height: 1.5;
    color: #333;
}
.container {
    max-width: 1100px;
    margin: auto;
    padding: 0 15px;
}
.feed { padding: 30px 0; }
.feed-top { margin-bottom: 30px; }
.feed-item { padding: 15px 0; border-bottom: 1px solid #eee; }
.feed-item-left { width: 60px; margin-right: 15px; }
.feed-item-left img { width: 100%; border-radius: 50%; }
.feed-item-right { width: calc(100% - 75px); }
.feed-item-right-top { margin-bottom: 10px; }
.feed-item-right-top-left { margin-right: 10px; }
.feed-item-right-top-right { cursor: pointer; }
.feed-item-right-bottom { margin-bottom: 10px; }
.feed-item-right-bottom p { margin-bottom: 0; }
.feed-item-right-bottom-2 { margin-bottom: 10px; }
.feed-item-right-bottom-2-left { cursor: pointer; margin-right: 10px; }
.feed-item-right-bottom-2-right { cursor: pointer; }
.sidebar { padding: 30px 0; }
.sidebar-item { margin-bottom: 30px; }
.sidebar-item h4 { margin-bottom: 10px; }
"""
        static_js_content = """
// SCRIPTS
$(document).ready(function () {
    AOS.init();
});
var swiper = new Swiper('.swiper-container', {
    loop: true,
    autoplay: { delay: 2500, disableOnInteraction: false, },
    slidesPerView: 'auto',
    pagination: { el: '.swiper-pagination', clickable: true, },
    navigation: { nextEl: '.swiper-button-next', prevEl: '.swiper-button-prev', },
});
""" 
        StaticFile.objects.create(project=self.project, path="static/css/styles.css", file=ContentFile(static_css_content, name="styles.css"))
        StaticFile.objects.create(project=self.project, path="static/js/scripts.js", file=ContentFile(static_js_content, name="scripts.js"))
        StaticFile.objects.create(project=self.project, path="static/images/user.jpg", file=ContentFile(b"dummy image content", name="user.jpg"))

        feed_html_content = """{% load static %}
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Feed</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" integrity="sha384-IGs9eLQVxqaTP3GdesLRiJ4D+1Rz5F2pqGJrRdfR7p07IrjIq4aWGVqd/9Ur+OpD4" crossorigin="anonymous">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/animate.css/4.1.1/animate.min.css">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/aos/2.3.4/aos.css">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/Swiper/8.0.7/swiper-bundle.min.css">
    <link rel="stylesheet" href="{% static 'css/styles.css' %}">
</head>
<body>
    <div id="top-bar" class="container">
        <div class="row">
            <div class="col-md-6 d-flex align-items-center">
                <div class="logo">
                    <a href="index.html" class="logo-text">Engineers</a>
                </div>
            </div>
            <div class="col-md-6">
                <div class="top-bar-right d-flex justify-content-end align-items-center">
                    <div class="social-logo mr-4">
                        <a href="#"><i class="fab fa-facebook-f"></i></a>
                        <a href="#"><i class="fab fa-twitter"></i></a>
                        <a href="#"><i class="fab fa-instagram"></i></a>
                        <a href="#"><i class="fab fa-linkedin-in"></i></a>
                    </div>
                    <div class="user">
                        <a href="#" class="btn btn-sm btn-primary">Sign In</a>
                        <a href="#" class="btn btn-sm btn-light">Sign Up</a>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <nav class="navbar navbar-expand-lg navbar-light bg-light">
        <div class="container">
            <a class="navbar-brand" href="index.html">Engineers</a>
            <button class="navbar-toggler" type="button" data-toggle="collapse" data-target="#navbarNav" aria-controls="navbarNav" aria-expanded="false" aria-label="Toggle navigation">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="navbarNav">
                <ul class="navbar-nav ml-auto">
                    <li class="nav-item active">
                        <a class="nav-link" href="index.html">Home <span class="sr-only">(current)</span></a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="about.html">About</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="services.html">Services</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="blog.html">Blog</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="contact.html">Contact</a>
                    </li>
                </ul>
            </div>
        </div>
    </nav>
    <div class="feed container">
        <div class="row">
            <div class="col-md-8">
                <div class="feed-top d-flex justify-content-between align-items-center">
                    <div class="feed-top-left">
                        <h3>Feed</h3>
                    </div>
                    <div class="feed-top-right">
                        <button class="btn btn-primary">Create Post</button>
                    </div>
                </div>
                <div class="feed-main">
                    <div class="feed-item d-flex align-items-center">
                        <div class="feed-item-left">
                            <img src="{% static 'images/user.jpg' %}" alt="User">
                        </div>
                        <div class="feed-item-right">
                            <div class="feed-item-right-top d-flex justify-content-between align-items-center">
                                <div class="feed-item-right-top-left">
                                    <h4>John Doe</h4>
                                    <p>1 hour ago</p>
                                </div>
                                <div class="feed-item-right-top-right">
                                    <i class="fas fa-ellipsis-h"></i>
                                </div>
                            </div>
                            <div class="feed-item-right-bottom">
                                <p>Lorem ipsum dolor sit amet, consectetur adipiscing elit. Integer nec odio. Praesent libero. Sed cursus ante dapibus diam. Sed nisi. Nulla quis sem at nibh elementum imperdiet. Duis sagittis ipsum. Praesent mauris.</p>
                            </div>
                            <div class="feed-item-right-bottom-2 d-flex justify-content-between align-items-center">
                                <div class="feed-item-right-bottom-2-left">
                                    <i class="fas fa-thumbs-up"></i>
                                    <p>Like</p>
                                </div>
                                <div class="feed-item-right-bottom-2-right">
                                    <i class="fas fa-comment"></i>
                                    <p>Comment</p>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="feed-item d-flex align-items-center">
                        <div class="feed-item-left">
                            <img src="{% static 'images/user.jpg' %}" alt="User">
                        </div>
                        <div class="feed-item-right">
                            <div class="feed-item-right-top d-flex justify-content-between align-items-center">
                                <div class="feed-item-right-top-left">
                                    <h4>John Doe</h4>
                                    <p>1 hour ago</p>
                                </div>
                                <div class="feed-item-right-top-right">
                                    <i class="fas fa-ellipsis-h"></i>
                                </div>
                            </div>
                            <div class="feed-item-right-bottom">
                                <p>Lorem ipsum dolor sit amet, consectetur adipiscing elit. Integer nec odio. Praesent libero. Sed cursus ante dapibus diam. Sed nisi. Nulla quis sem at nibh elementum imperdiet. Duis sagittis ipsum. Praesent mauris.</p>
                            </div>
                            <div class="feed-item-right-bottom-2 d-flex justify-content-between align-items-center">
                                <div class="feed-item-right-bottom-2-left">
                                    <i class="fas fa-thumbs-up"></i>
                                    <p>Like</p>
                                </div>
                                <div class="feed-item-right-bottom-2-right">
                                    <i class="fas fa-comment"></i>
                                    <p>Comment</p>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="feed-item d-flex align-items-center">
                        <div class="feed-item-left">
                            <img src="{% static 'images/user.jpg' %}" alt="User">
                        </div>
                        <div class="feed-item-right">
                            <div class="feed-item-right-top d-flex justify-content-between align-items-center">
                                <div class="feed-item-right-top-left">
                                    <h4>John Doe</h4>
                                    <p>1 hour ago</p>
                                </div>
                                <div class="feed-item-right-top-right">
                                    <i class="fas fa-ellipsis-h"></i>
                                </div>
                            </div>
                            <div class="feed-item-right-bottom">
                                <p>Lorem ipsum dolor sit amet, consectetur adipiscing elit. Integer nec odio. Praesent libero. Sed cursus ante dapibus diam. Sed nisi. Nulla quis sem at nibh elementum imperdiet. Duis sagittis ipsum. Praesent mauris.</p>
                            </div>
                            <div class="feed-item-right-bottom-2 d-flex justify-content-between align-items-center">
                                <div class="feed-item-right-bottom-2-left">
                                    <i class="fas fa-thumbs-up"></i>
                                    <p>Like</p>
                                </div>
                                <div class="feed-item-right-bottom-2-right">
                                    <i class="fas fa-comment"></i>
                                    <p>Comment</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="sidebar">
                    <div class="sidebar-item">
                        <h4>About</h4>
                        <p>Lorem ipsum dolor sit amet, consectetur adipiscing elit. Integer nec odio. Praesent libero. Sed cursus ante dapibus diam. Sed nisi. Nulla quis sem at nibh elementum imperdiet. Duis sagittis ipsum. Praesent mauris.</p>
                    </div>
                    <div class="sidebar-item">
                        <h4>Categories</h4>
                        <ul>
                            <li><a href="#">Web Design</a></li>
                            <li><a href="#">Web Development</a></li>
                            <li><a href="#">SEO</a></li>
                            <li><a href="#">Content Writing</a></li>
                            <li><a href="#">Graphic Design</a></li>
                        </ul>
                    </div>
                    <div class="sidebar-item">
                        <h4>Tags</h4>
                        <ul>
                            <li><a href="#">Web Design</a></li>
                            <li><a href="#">Web Development</a></li>
                            <li><a href="#">SEO</a></li>
                            <li><a href="#">Content Writing</a></li>
                            <li><a href="#">Graphic Design</a></li>
                        </ul>
                    </div>
                    <div class="sidebar-item">
                        <h4>Recent Posts</h4>
                        <ul>
                            <li><a href="#">Web Design</a></li>
                            <li><a href="#">Web Development</a></li>
                            <li><a href="#">SEO</a></li>
                            <li><a href="#">Content Writing</a></li>
                            <li><a href="#">Graphic Design</a></li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <footer class="footer">
        <div class="container">
            <div class="row">
                <div class="col-md-6">
                    <div class="footer-left">
                        <p>Copyright © 2022 Engineers. All Rights Reserved.</p>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="footer-right">
                        <ul class="list-unstyled d-flex justify-content-end">
                            <li><a href="#">Home</a></li>
                            <li><a href="#">About</a></li>
                            <li><a href="#">Services</a></li>
                            <li><a href="#">Blog</a></li>
                            <li><a href="#">Contact</a></li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    </footer>
    <script src="https://code.jquery.com/jquery-3.5.1.slim.min.js" integrity="sha384-DfXdz2htPH0lsSSGFpoO9xmv/+/z7nU7ELJ6EeAZWlCmGKZk4M1RtIDZOt6Xq/YD" crossorigin="anonymous"></script>
    <script src="https://cdn.jsdelivr.net/npm/@popperjs/core@2.9.3/dist/umd/popper.min.js" integrity="sha384-eMNCOe7tC1doHpGoJtKh7z7lGz7fuP4F8nfdFvAOA6Gg/z6Y5J6XqqyGXYM2ntX5" crossorigin="anonymous"></script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.0/dist/js/bootstrap.min.js" integrity="sha384-cn7l7gDp0eyniUwwAZgrzD06kc/tftFf19TOAs2zVinnD/C7E91j9yyk5//jjpt/"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/aos/2.3.4/aos.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Swiper/8.0.7/swiper-bundle.min.js"></script>
    <script src="{% static 'js/scripts.js' %}"></script>
</body>
</html>
"""
        diff = {
            "templates/feed.html": feed_html_content,
            "static/css/styles.css": static_css_content,
            "static/js/scripts.js": static_js_content
        }
        self.change_request = AIChangeRequest.objects.create(
            id=86,
            project=self.project,
            diff=json.dumps(diff),
            prompt="Make my feed page look like https://templatemo.com/tm-590-topic-listing"
        )

    def test_preview_one_view_before(self):
        """Test PreviewOneView for mode=before (empty template)."""
        from rest_framework.test import APIClient
        client = APIClient()
        token = AccessToken.for_user(self.user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        url = reverse("preview-one", kwargs={"project_id": self.project.id, "change_id": self.change_request.id})
        response = client.get(url, {"mode": "before", "file": "templates/feed.html"})

        self.assertEqual(response.status_code, 404, f"Expected 404, got {response.status_code}")
        self.assertEqual(response.data["error"], "Template feed.html not found", f"Expected 'Template feed.html not found', got {response.data}")

    def test_preview_one_view_after(self):
        """Test PreviewOneView for mode=after (AI-generated template)."""
        from rest_framework.test import APIClient
        client = APIClient()
        token = AccessToken.for_user(self.user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        url = reverse("preview-one", kwargs={"project_id": self.project.id, "change_id": self.change_request.id})
        response = client.get(url, {"mode": "after", "file": "templates/feed.html"})

        self.assertEqual(response.status_code, 200, f"Expected 200, got {response.status_code}")
        content = response.content.decode("utf-8")
        self.assertIn('<title>Feed</title>', content, "Expected title 'Feed' in response")
        self.assertIn('href="/static/css/styles.css"', content, "Expected static CSS link")
        self.assertIn('src="/static/js/scripts.js"', content, "Expected static JS script")
        self.assertIn('John Doe', content, "Expected feed item with 'John Doe'")
        self.assertIn('Copyright © 2022 Engineers', content, "Expected footer copyright")

    def test_preview_one_view_static_files(self):
        """Test access to static files referenced in the template."""
        from rest_framework.test import APIClient
        client = APIClient()
        token = AccessToken.for_user(self.user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        static_paths = ["static/css/styles.css", "static/js/scripts.js", "static/images/user.jpg"]
        for path in static_paths:
            response = client.get(f"/{path}")
            self.assertEqual(response.status_code, 200, f"Expected 200 for {path}, got {response.status_code}")

    def test_preview_one_view_invalid_file(self):
        """Test PreviewOneView with an invalid file path."""
        from rest_framework.test import APIClient
        client = APIClient()
        token = AccessToken.for_user(self.user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        url = reverse("preview-one", kwargs={"project_id": self.project.id, "change_id": self.change_request.id})
        response = client.get(url, {"mode": "after", "file": "templates/nonexistent.html"})

        self.assertEqual(response.status_code, 404, f"Expected 404, got {response.status_code}")
        self.assertEqual(response.data["error"], "No content for templates/nonexistent.html in after mode", f"Expected 'No content' error, got {response.data}")

    def test_preview_one_view_unauthenticated(self):
        """Test PreviewOneView without authentication."""
        from rest_framework.test import APIClient
        client = APIClient()
        url = reverse("preview-one", kwargs={"project_id": self.project.id, "change_id": self.change_request.id})
        response = client.get(url, {"mode": "after", "file": "templates/feed.html"})

        self.assertEqual(response.status_code, 401, f"Expected 401, got {response.status_code}")
        self.assertIn("Authentication credentials were not provided", response.data["detail"], f"Expected auth error, got {response.data}")

if __name__ == "__main__":
    unittest.main(verbosity=2)