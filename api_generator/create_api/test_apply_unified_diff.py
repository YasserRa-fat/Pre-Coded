import logging
import re

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Updated apply_unified_diff function
def apply_unified_diff(original_lines: list, diff: str) -> list:
    try:
        result_lines = original_lines.copy()
        offset = 0

        # Match each hunk header + body in one shot
        hunk_re = re.compile(
            r'^@@\s*-(\d+),(\d+)\s+\+(\d+),(\d+)\s*@@(.*?)(?=^@@|\Z)',
            re.MULTILINE | re.DOTALL
        )

        for m in hunk_re.finditer(diff):
            old_start, old_count, new_start, new_count = map(int, m.groups()[:4])
            hunk_body = m.group(5).lstrip('\n')
            splice_at = old_start - 1 + offset

            # sanity check
            if old_start < 1 or old_start + old_count - 1 > len(result_lines):
                logger.error(
                    f"Hunk out of bounds: old_start={old_start}, old_count={old_count}, "
                    f"file_lines={len(result_lines)}"
                )
                return original_lines

            new_lines = []
            idx = splice_at

            for line in hunk_body.splitlines():
                if line.startswith('+'):
                    # insertion
                    new_lines.append(line[1:])

                elif line.startswith('-'):
                    # deletion: must match existing line
                    expected = line[1:]
                    if idx >= len(result_lines) or result_lines[idx] != expected:
                        logger.error(
                            f"Deletion mismatch at {idx+1}: expected={expected!r}, "
                            f"got={result_lines[idx] if idx < len(result_lines) else 'EOF'!r}"
                        )
                        return original_lines
                    idx += 1

                else:
                    # context (any non +/– line, even blank)
                    txt = line[1:] if line.startswith(' ') else line
                    if idx >= len(result_lines) or result_lines[idx] != txt:
                        logger.error(
                            f"Context mismatch at {idx+1}: expected={txt!r}, "
                            f"got={result_lines[idx] if idx < len(result_lines) else 'EOF'!r}"
                        )
                        return original_lines
                    new_lines.append(txt)
                    idx += 1

            # splice out the old lines, insert the new
            result_lines[splice_at:splice_at + old_count] = new_lines
            offset += len(new_lines) - old_count

        logger.debug(f"Applied diff successfully, result_lines={len(result_lines)}")
        return result_lines

    except Exception as e:
        logger.exception(f"Failed to apply unified diff: {e}")
        return original_lines

# Original feed.html content (Case 1: Without <nav>, matching diff's expectation)
original_content_case1 = """{% extends "base.html" %}


<!DOCTYPE HTML>
<!--
        Justice by gettemplates.co
        Twitter: http://twitter.com/gettemplateco
        URL: http://gettemplates.co
-->
<html>

{% load static %}


{% block content %}
  <body>

    <div class="gtco-loader"></div>

    <div id="page">
      <div id="gtco-logo"><a href="index.html">Engineers<span>.</span></a></div>
      <header id="gtco-header" class="gtco-cover" role="banner" style="background-image: url({% static 'images/img_1.jpg' %})" data-stellar-background-ratio="0.5">
        <div class="overlay"></div>
        <div class="container">
          <div class="row">
            <div class="col-md-7 text-left">
              <div class="display-t">
                <div class="display-tc animate-box" data-animate-effect="fadeInUp">
                  <span class="date-post">Feed</span>
                  <h1 class="mb30"><a href="#">Welcome {{request.user}}</a></h1>
                  {% if request.user.is_authenticated %}
                    <p><a href="{% url 'post_create' %}" class="text-link">Create a Post</a></p>
                  {% else %}
                    <p><a href="{% url 'register' %}" class="text-link">Register</a> or <a href="{% url 'login' %}" class="text-link">Login</a> to post</p>
                  {% endif %}
                </div>
              </div>
            </div>
          </div>
        </div>
      </header>
      <div id="gtco-main">
        <div class="container">
          <div class="row row-pb-md">
            <div class="col-md-12">
              <ul id="gtco-post-list">
                {% if posts %}
                  {% for p in posts %}
                    <li class="one-third entry animate-box" data-animate-effect="fadeIn">
                      <a href="{% url 'detail' p.id %}">
                        <div class="entry-img" style="background-image: url('{{p.image.url}}')"></div>
                        <div class="entry-desc">
                          <h3>{{p.title}}</h3>
                          <p>{{p.description}}.</p>
                        </div>
                      </a>
                      <a href="{% url 'detail' p.id %}" class="post-meta">{{p.user}} <span class="date-posted">{{p.created_at}}</span></a>
                    </li>
                  {% endfor %}
                {% else %}
                  <li class="one-third entry animate-box" data-animate-effect="fadeIn">
                    <a href="#" class="img" style="background-image: url({% static 'images/img_1.jpg' %})"></a>
                    <div class="entry-desc">
                      <h3><a href="#">Post Title</a></h3>
                      <p>Far far away, behind the word mountains, far from the countries Vokalia and Consonantia, there live the blind texts.</p>
                    </div>
                  </li>
                {% endif %}
              </ul>
            </div>
          </div>
          <div class="row">
            <div class="col-md-12 text-center">
              <nav aria-label="Page navigation">
                <ul class="pagination">
                  <li>
                    <a href="#" aria-label="Previous">
                      <span aria-hidden="true">«</span>
                    </a>
                  </li>
                  <li class="active"><a href="#">1</a></li>
                  <li><a href="#">2</a></li>
                  <li>
                    <a href="#" aria-label="Next">
                      <span aria-hidden="true">»</span>
                    </a>
                  </li>
                </ul>
              </nav>
            </div>
          </div>
        </div>
      </div>
      <footer id="gtco-footer" role="contentinfo">
        <div class="gtco-container">
          <div class="row row-pb-md">
            <div class="col-md-8 col-md-offset-2 text-center gtco-counter">
              <div class="col-md-3 col-sm-6 animate-box">
                <div class="feature-center">
                  <span class="counter js-counter" data-from="0" data-to="320" data-speed="5000" data-refresh-interval="50">320</span>
                  <span class="counter-label">Articles</span>
                </div>
              </div>
              <div class="col-md-3 col-sm-6 animate-box">
                <span class="counter js-counter" data-from="0" data-to="25" data-speed="5000" data-refresh-interval="50">25</span>
                <span class="counter-label">Topics</span>
              </div>
              <div class="col-md-3 col-sm-6 animate-box">
                <span class="counter js-counter" data-from="0" data-to="12" data-speed="5000" data-refresh-interval="50">12</span>
                <span class="counter-label">Members</span>
              </div>
            </div>
          </div>
        </div>
        <div id="gtco-subscribe" class="gtco-section">
          <div class="gtco-container">
            <div class="row animate-box">
              <div class="col-md-8 col-md-offset-2 text-center gtco-heading">
                <h2>Subscribe to our Newsletter</h2>
                <p>Far far away, behind the word mountains, far from the countries Vokalia and Consonantia, there live the blind texts.</p>
              </div>
              <div class="col-md-6 animate-box">
                <form class="form-inline qbstp-header-subscribe">
                  <div class="form-group">
                    <input type="text" class="form-control" id="email" placeholder="Enter your email">
                    <button type="submit" class="btn btn-primary">Subscribe</button>
                  </div>
                </form>
              </div>
            </div>
          </div>
        </div>
        <div id="gtco-copyright" role="contentinfo" class="gtco-container">
          <div class="row">
            <div class="col-md-12">
              <p><small class="block">© 2016 Free HTML5. All Rights Reserved.</small><small class="block">Designed by <a href="http://gettemplates.co/" target="_blank">GetTemplates.co</a> Demo Images: <a href="http://unsplash.com/" target="_blank">Unsplash</a></small></p>
            </div>
          </div>
        </div>
      </footer>
    </div>
  </body>
{% endblock %}
</html>
"""

# Original feed.html content (Case 2: With <nav>, from TemplateFile)
original_content_case2 = """{% extends "base.html" %}


<!DOCTYPE HTML>
<!--
        Justice by gettemplates.co
        Twitter: http://twitter.com/gettemplateco
        URL: http://gettemplates.co
-->
<html>

{% load static %}


{% block content %}
  <body>

    <div class="gtco-loader"></div>

    <div id="page">
      <nav class="gtco-nav" role="navigation">
        <div class="container">
          <div class="row">
            <div class="col-xs-2 text-left">
              <div id="gtco-logo"><a href="index.html">Engineers<span>.</span></a></div>
            </div>
            <div class="col-xs-10 text-right menu-1">
              <ul>
                <li class="active"><a href="#">Home</a></li>
                {% if request.user.is_authenticated %}
                  <li><a href="{% url 'logout' %}">Logout</a></li>
                  <li><a href="{% url 'home' %}">Profile</a></li>
                {% else %}
                  <li><a href="{% url 'login' %}">Login</a></li>
                  <li><a href="{% url 'register' %}">Register</a></li>
                {% endif %}
              </ul>
            </div>
          </div>
        </div>
      </nav>
      <header id="gtco-header" class="gtco-cover" role="banner" style="background-image: url({% static 'images/img_1.jpg' %})" data-stellar-background-ratio="0.5">
        <div class="overlay"></div>
        <div class="container">
          <div class="row">
            <div class="col-md-7 text-left">
              <div class="display-t">
                <div class="display-tc animate-box" data-animate-effect="fadeInUp">
                  <span class="date-post">Feed</span>
                  <h1 class="mb30"><a href="#">Welcome {{request.user}}</a></h1>
                  {% if request.user.is_authenticated %}
                    <p><a href="{% url 'post_create' %}" class="text-link">Create a Post</a></p>
                  {% else %}
                    <p><a href="{% url 'register' %}" class="text-link">Register</a> or <a href="{% url 'login' %}" class="text-link">Login</a> to post</p>
                  {% endif %}
                </div>
              </div>
            </div>
          </div>
        </div>
      </header>
      <div id="gtco-main">
        <div class="container">
          <div class="row row-pb-md">
            <div class="col-md-12">
              <ul id="gtco-post-list">
                {% if posts %}
                  {% for p in posts %}
                    <li class="one-third entry animate-box" data-animate-effect="fadeIn">
                      <a href="{% url 'detail' p.id %}">
                        <div class="entry-img" style="background-image: url('{{p.image.url}}')"></div>
                        <div class="entry-desc">
                          <h3>{{p.title}}</h3>
                          <p>{{p.description}}.</p>
                        </div>
                      </a>
                      <a href="{% url 'detail' p.id %}" class="post-meta">{{p.user}} <span class="date-posted">{{p.created_at}}</span></a>
                    </li>
                  {% endfor %}
                {% else %}
                  <li class="one-third entry animate-box" data-animate-effect="fadeIn">
                    <a href="#" class="img" style="background-image: url({% static 'images/img_1.jpg' %})"></a>
                    <div class="entry-desc">
                      <h3><a href="#">Post Title</a></h3>
                      <p>Far far away, behind the word mountains, far from the countries Vokalia and Consonantia, there live the blind texts.</p>
                    </div>
                  </li>
                {% endif %}
              </ul>
            </div>
          </div>
          <div class="row">
            <div class="col-md-12 text-center">
              <nav aria-label="Page navigation">
                <ul class="pagination">
                  <li>
                    <a href="#" aria-label="Previous">
                      <span aria-hidden="true">«</span>
                    </a>
                  </li>
                  <li class="active"><a href="#">1</a></li>
                  <li><a href="#">2</a></li>
                  <li>
                    <a href="#" aria-label="Next">
                      <span aria-hidden="true">»</span>
                    </a>
                  </li>
                </ul>
              </nav>
            </div>
          </div>
        </div>
      </div>
      <footer id="gtco-footer" role="contentinfo">
        <div class="gtco-container">
          <div class="row row-pb-md">
            <div class="col-md-8 col-md-offset-2 text-center gtco-counter">
              <div class="col-md-3 col-sm-6 animate-box">
                <div class="feature-center">
                  <span class="counter js-counter" data-from="0" data-to="320" data-speed="5000" data-refresh-interval="50">320</span>
                  <span class="counter-label">Articles</span>
                </div>
              </div>
              <div class="col-md-3 col-sm-6 animate-box">
                <span class="counter js-counter" data-from="0" data-to="25" data-speed="5000" data-refresh-interval="50">25</span>
                <span class="counter-label">Topics</span>
              </div>
              <div class="col-md-3 col-sm-6 animate-box">
                <span class="counter js-counter" data-from="0" data-to="12" data-speed="5000" data-refresh-interval="50">12</span>
                <span class="counter-label">Members</span>
              </div>
            </div>
          </div>
        </div>
        <div id="gtco-subscribe" class="gtco-section">
          <div class="gtco-container">
            <div class="row animate-box">
              <div class="col-md-8 col-md-offset-2 text-center gtco-heading">
                <h2>Subscribe to our Newsletter</h2>
                <p>Far far away, behind the word mountains, far from the countries Vokalia and Consonantia, there live the blind texts.</p>
              </div>
              <div class="col-md-6 animate-box">
                <form class="form-inline qbstp-header-subscribe">
                  <div class="form-group">
                    <input type="text" class="form-control" id="email" placeholder="Enter your email">
                    <button type="submit" class="btn btn-primary">Subscribe</button>
                  </div>
                </form>
              </div>
            </div>
          </div>
        </div>
        <div id="gtco-copyright" role="contentinfo" class="gtco-container">
          <div class="row">
            <div class="col-md-12">
              <p><small class="block">© 2016 Free HTML5. All Rights Reserved.</small><small class="block">Designed by <a href="http://gettemplates.co/" target="_blank">GetTemplates.co</a> Demo Images: <a href="http://unsplash.com/" target="_blank">Unsplash</a></small></p>
            </div>
          </div>
        </div>
      </footer>
    </div>
  </body>
{% endblock %}
</html>
"""

# Unified diff from AI response
unified_diff = """--- a/feed.html
+++ b/feed.html
@@ -1,10 +1,15 @@
 {% extends "base.html" %}

 <!DOCTYPE HTML>
 <!--
   Justice by gettemplates.co
    Twitter: http://twitter.com/gettemplateco
     URL: http://gettemplates.co
 -->
 <html>

 {% load static %}

@@ -22,6 +27,11 @@
          <div class="gtco-loader"></div>

             <div id="page">
+                    <nav class="gtco-nav" role="navigation">
+                            <div class="container">
+                              <div class="row">
+                                           <div class="col-xs-2 text-left">
     <div id="gtco-logo"><a href="index.html">Engineers<span>.</span></a></div>
                          </div>
@@ -30,6 +39,22 @@
                                            <div class="col-xs-10 text-right menu-1">
                                                     <ul>
+                                   <li class="active"><a href="#">Home</a></li>
+                                                        {% if request.user.is_authenticated %}
+                                                                <li><a href="{% url 'logout' %}">Logout</a></li>
+                                                        <li><a href="{% url 'home' %}">Profile</a></li>
+                                                       {%else%}
+                                                              <li><a href="{% url 'login' %}">Login</a></li>
+                                                                <li><a href="{% url 'register' %}">Register</a></li>
+                                                          {%endif%}
+      </ul>
                                         </div>
                                       </div>
@@ -40,7 +65,7 @@
                               </div>
                       </div>
               </div>
-  <header id="gtco-header" class="gtco-cover" role="banner" style="background-image: url({% static 'images/img_1.jpg' %})" data-stellar-background-ratio="0.5">
+ <header id="gtco-header" class="gtco-cover" role="banner" style="background-image: url({% static 'images/img_1.jpg' %})" data-stellar-background-ratio="0.5" data-stellar-vertical-offset="0">
         <div class="overlay"></div>
      <div class="container">
                     <div class="row">
@@ -49,12 +74,12 @@
               <div class="col-md-7 text-left">
                                    <div class="display-t">
      <div class="display-tc animate-box" data-animate-effect="fadeInUp">
-                                 <span class="date-post">Feed</span>
+                                                 <span class="date-post">Posts</span>
                                                  <h1 class="mb30"><a href="#">Welcome {{request.user}}</a></h1>
                                                      {% if request.user.is_authenticated %}
                                                  <p><a href="{% url 'post_create' %}" class="text-link">Create a Post</a></p>
                                                        {%else%}
                                                        <p><a href="{% url 'register' %}" class="text-link">Register</a> or <a href="{% url 'login' %}" class="text-link">Login</a> to post</p>
   {%endif%}
                                             </div>
                                       </div>
@@ -63,7 +88,7 @@
                       </div>
               </div>
       </header>
-<div id="gtco-main">
+<div id="gtco-main" class="gtco-container">
            <div class="container">
                       <div class="row row-pb-md">
                                <div class="col-md-12">
@@ -73,7 +98,7 @@
                                    <ul id="gtco-post-list">
             {% if posts %}

-                                                      {% for p in posts %}
+           {% for p in posts|slice:"::3" %}
                                                            <li class="one-third entry animate-box" data-animate-effect="fadeIn"> <!--ONE THIRD-->
                        <a href="{% url 'detail' p.id %}"
                                                                     <div class="entry-img" style="background-image: url('{{p.image.url}}')"></div>
@@ -81,12 +106,12 @@
<div class="entry-desc">
                                                                            <h3>{{p.title}}</h3>
                                                                            <p>{{p.description}}.</p>
-                                                                       </div>
+         </div>
                                                                </a>
                           <a href="{% url 'detail' p.id %}" class="post-meta">{{p.user}} <span class="date-posted">{{p.created_at}}</span></a>
                                                       </li>
                          {% endfor %}
                                          {% else %}
@@ -95,7 +120,7 @@
                 <li class="one-third entry animate-box" data-animate-effect="fadeIn"> <!--ONE THIRD-->
              <a href="#" class="img" style="background-image: url({% static 'images/img_1.jpg' %})"></a>
       <div class="entry-desc">
-                                                                    <h3><a href="#">Post Title</a></h3>
+                                                                   <h3><a href="#">No Posts Yet</a></h3>
                                                                 <p>Far far away, behind the word mountains, far from the countries Vokalia and Consonantia, there live the blind texts.</p>
                                                                </div>
                         </li>
@@ -103,7 +128,7 @@
                                            </ul>
                          </div>
                        </div>
-                       <div class="row">
+                  <div class="row gtco-space">
                          <div class="col-md-12 text-center">
          <nav aria-label="Page navigation">
                                          <ul class="pagination">
@@ -111,7 +136,7 @@
                                                  <li>
                           <a href="#" aria-label="Previous">
                                                                  <span aria-hidden="true">«</span>
-                                                             </a>
+                                                    </a>
                                           </li>
                                                 <li class="active"><a href="#">1</a></li>
  <li><a href="#">2</a></li>
@@ -120,7 +145,7 @@
                                                     <li>
                                                            <a href="#" aria-label="Next">
     <span aria-hidden="true">»</span>
-                                                             </a>
+                                                    </a>
                                           </li>
                                         </ul>
                                        </nav>
@@ -128,7 +153,7 @@
                     </div>
               </div>
       </div>
-<footer id="gtco-footer" role="contentinfo">
+<footer id="gtco-footer" role="contentinfo" class="gtco-container">
      <div class="gtco-container">
               <div class="row row-pb-md">
                  <div class="col-md-8 col-md-offset-2 text-center gtco-counter">
@@ -137,7 +162,7 @@
                  <div class="col-md-3 col-sm-6 animate-box">
                                         <div class="feature-center">
                                          <span class="counter js-counter" data-from="0" data-to="320" data-speed="5000" data-refresh-interval="50">320</span>
-                            <span class="counter-label">Articles</span>
+                                         <span class="counter-label">Posts</span>
                                      </div>
                               </div>
                          <div class="col-md-3 col-sm-6 animate-box">
@@ -145,7 +170,7 @@
     <span class="counter js-counter" data-from="0" data-to="25" data-speed="5000" data-refresh-interval="50">25</span>
                                     <span class="counter-label">Topics</span>
    </div>
-                                <div class="col-md-3 col-sm-6 animate-box">
+                  <div class="col-md-3 col-sm-6 animate-box">
                                         <span class="counter js-counter" data-from="0" data-to="12" data-speed="5000" data-refresh-interval="50">12</span>
                                       <span class="counter-label">Members</span>
                   </div>
@@ -153,7 +178,7 @@
                   </div>
               </div>
       </div>
-<div id="gtco-subscribe" class="gtco-section">
+<div id="gtco-subscribe" class="gtco-section gtco-container">
    <div class="gtco-container">
               <div class="row animate-box">
                <div class="col-md-8 col-md-offset-2 text-center gtco-heading">
@@ -162,7 +187,7 @@
                  <h2>Subscribe to our Newsletter</h2>
                          <p>Far far away, behind the word mountains, far from the countries Vokalia and Consonantia, there live the blind texts.</p>
                     </div>
-                  <div class="col-md-6 animate-box">
+                 <div class="col-md-6 animate-box gtco-animate-when-almost-visible">
                           <form class="form-inline qbstp-header-subscribe">
                                     <div class="form-group">
                     <input type="text" class="form-control" id="email" placeholder="Enter your email">
@@ -171,7 +196,7 @@
                                          <button type="submit" class="btn btn-primary">Subscribe</button>
                                    </div>
                               </form>
-       </div>
+               </div>
       </div>
       </div>
</footer>
@@ -180,7 +205,7 @@
<div id="gtco-copyright" role="contentinfo" class="gtco-container">
     <div class="row">
          <div class="col-md-12">
-                       <p><small class="block">© 2016 Free HTML5. All Rights Reserved.</small><small class="block">Designed by <a href="http://gettemplates.co/" target="_blank">GetTemplates.co</a> Demo Images: <a href="http://unsplash.com/" target="_blank">Unsplash</a></small></p>
+                   <p><small class="block">© 2023 Engineers. All Rights Reserved.</small><small class="block">Designed by <a href="https://github.com/yourusername" target="_blank">Your Name</a> Demo Images: <a href="https://unsplash.com/" target="_blank">Unsplash</a></small></p>
              </div>
  </div>
</div>
"""

# Test Case 1: Apply diff to content without <nav>
print("=== Testing Case 1: Content without <nav> ===")
original_lines_case1 = original_content_case1.splitlines()
result_lines_case1 = apply_unified_diff(original_lines_case1, unified_diff)
print("\nResult (Case 1):\n")
print('\n'.join(result_lines_case1))

# Test Case 2: Apply diff to content with <nav>
print("\n=== Testing Case 2: Content with <nav> ===")
original_lines_case2 = original_content_case2.splitlines()
result_lines_case2 = apply_unified_diff(original_lines_case2, unified_diff)
print("\nResult (Case 2):\n")
print('\n'.join(result_lines_case2))