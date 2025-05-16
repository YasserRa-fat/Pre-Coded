```javascript
document.addEventListener('DOMContentLoaded', function() {
    var ctx = document.getElementById('analyticsChart').getContext('2d');
    var analyticsChart = new Chart(ctx, {
        type: 'line',
        data: comments_data,
        options: {
            responsive: true,
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'day'
                    }
                },
                y: {
                    beginAtZero: true
                }
            }
        }
    });
});
```

File: static/css/main.css
Required Change: Style the graph container.

```css
#analyticsChartContainer {
    width: 100%;
    height: 400px;
    border: 1px solid #ccc;
    border-radius: 5px;
    overflow: hidden;
}
```

File: templates/base.html
Required Change: Add the canvas element for the analytics graph.

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}My Django Project{% endblock %}</title>
    {% block extra_head %}{% endblock %}
    <link rel="stylesheet" href="{% static 'css/main.css' %}">
</head>
<body>
    <div id="analyticsChartContainer">
        <canvas id="analyticsChart"></canvas>
    </div>
    {% block content %}{% endblock %}
    <script src="{% static 'js/main.js' %}"></script>
</body>
</html>
```

Note: The `comments_data` variable should be passed to the template context by the Django view.