// Feed analytics functionality
document.addEventListener('DOMContentLoaded', function() {
    // Get analytics canvas element
    const analyticsCanvas = document.getElementById('analytics');
    if (!analyticsCanvas) return;

    // Initialize Chart.js
    const ctx = analyticsCanvas.getContext('2d');
    
    // Default data structure
    const defaultData = {
        labels: [],
        datasets: [{
            label: 'Comments',
            data: [],
            backgroundColor: 'rgba(75, 192, 192, 0.2)',
            borderColor: 'rgba(75, 192, 192, 1)',
            borderWidth: 1
        }]
    };

    // Chart configuration
    const config = {
        type: 'bar',
        data: defaultData,
        options: {
            responsive: true,
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    };

    // Create chart instance
    const analyticsChart = new Chart(ctx, config);

    // Function to update chart data
    window.updateAnalytics = function(labels, data) {
        analyticsChart.data.labels = labels;
        analyticsChart.data.datasets[0].data = data;
        analyticsChart.update();
    };
}); 