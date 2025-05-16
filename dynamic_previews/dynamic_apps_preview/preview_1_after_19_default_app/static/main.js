```javascript
document.addEventListener('DOMContentLoaded', function() {
    var ctx = document.getElementById('analyticsChart').getContext('2d');
    var analyticsChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: comments_data.dates,
            datasets: [{
                label: 'Number of Comments',
                data: comments_data.counts,
                backgroundColor: 'rgba(75, 192, 192, 0.2)',
                borderColor: 'rgba(75, 192, 192, 1)',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            scales: {
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
Required Change: Load the static files.

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Django Project</title>
    <!-- Load CSS -->
    <link rel="stylesheet" href="{% static 'css/main.css' %}">
</head>
<body>
    <!-- Your HTML content -->

    <!-- Load JS -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="{% static 'js/main.js' %}"></script>
</body>
</html>
```