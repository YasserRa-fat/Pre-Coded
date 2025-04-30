class FloatingBotMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Only inject into HTML responses
        if 'text/html' in response.get('Content-Type', ''):
            content = response.content.decode('utf-8')
            if '</body>' in content:
                script_tag = '<script src="/static/js/floating-bot.js"></script></body>'
                content = content.replace('</body>', script_tag)
                response.content = content.encode('utf-8')

        return response
