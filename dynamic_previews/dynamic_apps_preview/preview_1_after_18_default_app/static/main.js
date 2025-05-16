Updated File: static/js/main.js
Content:
```javascript
$(document).ready(function () {
  // Analytics data
  const analyticsData = {
    labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
    series: [
      [54, 78, 43, 92, 65, 48, 76, 56, 87, 49, 74, 67], // Series A
      [34, 56, 23, 45, 78, 34, 87, 67, 54, 23, 45, 67], // Series B
      [78, 45, 98, 34, 67, 89, 56, 78, 45, 98, 34, 67], // Series C
    ],
  };

  // Set up Chart.js
  const analyticsChart = new Chart('analytics-graph', {
    type: 'line',
    data: analyticsData,
    options: {
      lineSmooth: Chart.helpers.config.lineSmooth.bezierCurve,
      low: 0,
      high: 100,
      showArea: true,
      height: '400px',
      width: '100%',
      scaleY: {
        reverse: false,
        ticks: {
          min: 0,
          max: 100,
          callback: function (value) {
            return value + '%';
          },
        },
      },
      axisY: {
        showGrid: true,
        grid: {
          borderDash: [3],
          borderDashOffset: [2],
          color: '#e5e5e5',
          zeroLineColor: '#e5e5e5',
          drawBorder: false,
        },
        offset: 0,
      },
      tooltips: {
        intersect: false,
      },
      hover: {
        intersect: true,
      },
      legend: {
        display: false,
      },
    },
  });
});
```
```
This updated `main.js` file now includes the logic to fetch and display the analytics data using Chart.js. The analytics data is hardcoded in this example, but you can replace it with data fetched from an API or any other data source.