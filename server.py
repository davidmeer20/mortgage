# Import the necessary libraries
import tornado.ioloop
import tornado.web
import json

# Define the request handlers

class MainHandler(tornado.web.RequestHandler):
    def get(self):
        self.write("Hello, the world")

    def post(self):
        data = json.loads(self.request.body)
        self.write(data)

    def put(self):
        data = json.loads(self.request.body)
        self.write(data)

    def delete(self):
        data = json.loads(self.request.body)

# Define the application

def make_app():
    return tornado.web.Application([
        (r"/myendpoint", MainHandler),
    ])

# Run the application

if __name__ == "__main__":
    app = make_app()
    app.listen(8888)
    tornado.ioloop.IOLoop.current().start()
