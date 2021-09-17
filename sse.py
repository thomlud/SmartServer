import queue

def format_sse(data: str, event=None) -> str:
    msg = f'data: {data}\n\n'
    if event is not None:
        msg = f'event: {event}\n{msg}'
    return msg

# # # SSE Function message announcer # # #
class MessageAnnouncer:
    """ listen() will be called by clients to receive notifications
        announce() takes messages and announces them to listeners
    """
    def __init__(self):
        self.listeners = []

    def listen(self):
        q = queue.Queue(maxsize=5)
        self.listeners.append(q)
        return q

    def announce(self, msg):
        for i in reversed(range(len(self.listeners))):
            try:
                self.listeners[i].put_nowait(msg)
            except queue.Full:
                del self.listeners[i]


announcer = MessageAnnouncer()
announcer.announce(msg=format_sse(data="reload"))

# flask sse listener to include into app
'''
@app.route('/listen', methods=['GET'])
def listen():
    def stream():
        messages = announcer.listen()  # returns a queue.Queue
        while True:
            msg = messages.get()  # blocks until a new message arrives
            yield msg
    return Response(stream(), mimetype='text/event-stream')
'''

# javascript function to receive sse announces and act on page
'''
<script>
   function sse() {
        var source = new EventSource('/listen');
        var out = document.getElementById('out');
        source.onmessage = function(e) {
          if (e.data.includes('reload')) {
            window.location.reload(true);
          } else {
            out.textContent =  e.data + '\n' + out.textContent;
            alert(e.data);
          }
          out.textContent =  e.data + '\n' + out.textContent;
        };
   }
   sse();
</script>'''