# senti

The SENTI runtime package. See the [project README](../README.md) for features, setup and configuration.

```python
from senti import SentiService

assistant = SentiService(approval_handler=my_approval, event_sink=print)
assistant.start()                      # connects to Ollama and pre-loads the session in the background
reply = assistant.send_message("What's using my RAM?")
print(reply["response"])
```

`approval_handler(tool_name, arguments, risk, preview) -> bool` is called for every state-changing action after it has been simulated; `event_sink(event)` receives the lifecycle events documented in `senti/events.py`.
