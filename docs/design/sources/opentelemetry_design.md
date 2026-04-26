---
title: "OpenTelemetry and Python: A Complete Instrumentation Guide"
published: 2022-03-23T09:07:46.000-04:00
updated: 2024-04-18T14:18:03.000-04:00
excerpt: "Learn how to instrument Python code with OpenTelemetry, both manually and using auto-instrumentation. "
tags: Monitoring & Alerting, Engineering, Python, #Callout-technical
authors: James Blackwood-Sewell
---

> **TimescaleDB is now Tiger Data.**

OpenTelemetry is considered by many the future of instrumentation, and it’s not hard to understand why. In a world where successful companies are software companies, the need to collect observations from running code is almost universal. Through metrics, logs, and traces, observability data gives us the information we need to inspect how our applications run—and thanks to projects like OpenTelemetry, observability is becoming accessible to everyone.

In the past, collecting and analyzing observability data meant negotiating a challenging landscape: developers had to either buy into a walled garden provided by a commercial vendor or sacrifice interoperability by attempting to combine multiple open-source projects, each with a different instrumentation API and ecosystem.

The open source path often resulted in combining components like Prometheus (metrics), Elastic (logs), and Jaeger (traces), but using many systems often felt complex with multiple instrumentation syntaxes, multiple outputs, multiple query languages, and multiple backends.

[OpenTelemetry](https://opentelemetry.io) promises to solve this complexity by providing a vendor-agnostic standard for observability, allowing users to decouple instrumentation and routing from storage and query. The OpenTelemetry API (which defines how OpenTelemetry is used) and language SDKs (which define the specific implementation of the API for a language) generate observability data; this allows backends to be mixed and matched as needed, which aims to be a unified backend for all OpenTelemetry data.

This approach allows OpenTelemetry users to concentrate on instrumentation as a separate concern. Users of OpenTelemetry can implement instrumentation without having to know where the data is going to be stored, what format it will be stored in, or how it will eventually be queried. As we will see below, developers can even take advantage of [auto-instrumentation](https://opentelemetry.io/docs/instrumentation/python/automatic/): the codebase doesn’t need to be explicitly instrumented for a number of languages.

## OpenTelemetry Meets Python

Among the three observability data types supported by OpenTelemetry (metrics, traces, and logs), traces are especially useful for understanding the behavior of distributed systems. OpenTelemetry tracing allows developers to create spans, representing a timed code block. Each span includes key-value pairs—called attributes—to help describe what the span represents, links to other spans, and events that denote timestamps within the span. By visualizing and querying the spans, developers gain a complete overview of their systems, helping them identify problems quickly when they arise.

In this post, we will explore how we would instrument a Python application to emit tracing data (metric and log data interfaces are not stable quite yet). Then, we will examine:

-   How auto-instrumentation of the same codebase works.
-   The differences with manual instrumentation.
-   How to mix manual instrumentation with auto-instrumentation.
-   How to add information about exceptions.

This guide focuses on Python code, but it is worth mentioning that OpenTelemetry offers [instrumentation SDKs](https://opentelemetry.io/docs/instrumentation/) for many languages, like Java, [JavaScript](https://opentelemetry.io/docs/instrumentation/js/), [Go](https://opentelemetry.io/docs/instrumentation/go/), [Rust](https://opentelemetry.io/docs/instrumentation/rust/), and more. In the case of auto-instrumentation, it is supported by a few languages ([Python](https://opentelemetry.io/docs/instrumentation/python/automatic/), [Java](https://opentelemetry.io/docs/instrumentation/java/automatic/), [Node](https://opentelemetry.io/docs/instrumentation/js/instrumentation/), [Ruby](https://opentelemetry.io/docs/instrumentation/ruby/automatic/), and [.NET](https://opentelemetry.io/docs/instrumentation/net/automatic/)) with plans of adding more in the future.

## The Example Python App

We will start with a supremely simple Python app that uses Flask to expose a route that models rolling a dice one or more times and summing the output. The default case rolls a 10- sided dice once, with request arguments that allow rolling extra times.

```Python
from random import randint
from flask import Flask, request

app = Flask(__name__)

@app.route("/roll")
def roll():
    sides = int(request.args.get('sides'))
    rolls = int(request.args.get('rolls'))
    return roll_sum(sides,rolls)


def roll_sum(sides, rolls):
    sum = 0
    for r in range(0,rolls):
        result = randint(1,sides)
        sum += result
    return str(sum)
```

Before we continue, let’s ensure that we configured our development environment correctly. You’ll need Python 3.x installed on your machine and Python pip to install packages. We will use a Python virtual environment to ensure our workspace is clean.

To start, we will need to install Flask, which will also install the Flask binary, which we will use to run our app:

```shell
mkdir otel-instrumentation
cd otel-instrumentation
python3 -m venv .
source ./bin/activate
pip install flask
```

Now that we have our environment ready, copy the code from above into a file called `app.py`.

## Adding OpenTelemetry Instrumentation Manually

We can run the Flask application using the flask command, then use curl to access the route, providing both a number of rolls and the number of sides for each dice. As expected, it will return the sum of the rolls (in this case, a single roll).

In one terminal, run our Flask app:

```shell
flask run
```

And in another terminal, use curl to request the roll route from our Flask app:

```shell
curl 'http://127.0.0.1:5000/roll?sides=10&rolls=1'
```

To instrument this code, we need to add the following OpenTelemetry setup that will let us create traces and spans and export them to the console. Add this to the top of your Python app:

```Python
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.export import ConsoleSpanExporter

provider = TracerProvider()
processor = BatchSpanProcessor(ConsoleSpanExporter())
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)
```

There are three concepts at play here, a provider, a processor, and a tracer.

-   A provider (in this case TracingProvider) is the API entry point that holds configuration.
-   A processor defines the method of sending the created elements (spans) onward.
-   A tracer is an actual object which creates the spans.

The code creates a provider, adds a processor to it, then configures the local tracing environment to use these.

In our case, the processor is writing to the local console—you’ll probably note that this is hardcoded, which somewhat dilutes the OpenTelemetry mantra of removing downstream concerns from observability generation.

If we wanted to send our traces elsewhere, we would need to alter this code. This is usually side-stepped by sending to an OpenTelemetry Collector—which can be thought of as a standalone proxy that receives inputs, processes them if needed, and exports them to one or more downstream locations. In our situation, we will stick with the console.

We will also need to make sure that we have the `opentelemetry-distro` (which will pull in the SDK and the API, as well as make the `opentelemetry-bootstrap` and `opentelemetry-instrument` commands available) Python package installed by running the following command:

```shell
pip install opentelemetry-distro
```

Once we have the components installed and the API configured, we can use the tracer object to add a span to our Flask route. Replace the app route with the following updated code:

```Python
@app.route("/roll")
def roll():
    with tracer.start_as_current_span("server_request"):
        sides = int(request.args.get('sides'))
        rolls = int(request.args.get('rolls'))
        return roll_sum(sides,rolls)
```

That will make a span lasting for the length of the block on each call to the Flask route. If we stop-start the Flask application and access the endpoint again, we will see the OpenTelemetry tracing data written to the console.

```json
{
    "name": "server_request",
    "context": {
        "trace_id": "0xae7539e266baff8ecab1c065f70839d3",
        "span_id": "0x760ae3a7cee38441",
        "trace_state": "[]"
    },
    "kind": "SpanKind.INTERNAL",
    "parent_id": null,
    "start_time": "2022-03-11T02:27:08.090530Z",
    "end_time": "2022-03-11T02:27:08.090584Z",
    "status": {
        "status_code": "UNSET"
    },
    "attributes": {},
    "events": [],
    "links": [],
    "resource": {
        "telemetry.sdk.language": "python",
        "telemetry.sdk.name": "opentelemetry",
        "telemetry.sdk.version": "1.9.1",
        "service.name": "unknown_service"
    }
}
```

We have now created a span. We can see that there is not much helpful information other than the span ID (which will be referenced in child spans), the trace ID (which groups related spans), and the start and end times. We can add some attributes and an event per roll by changing the code again. Replace the route and the roll\_sum definitions with the following:

```Python
@app.route("/roll")
def roll():
    with tracer.start_as_current_span(
        "server_request", 
        attributes={ "endpoint": "/roll" } 
    ):

        sides = int(request.args.get('sides'))
        rolls = int(request.args.get('rolls'))
        return roll_sum(sides,rolls)

def roll_sum(sides, rolls):
    span = trace.get_current_span()
    sum = 0
    for r in range(0,rolls):
        result = randint(1,sides)
        span.add_event( "log", {
            "roll.sides": sides,
            "roll.result": result,
        })
        sum += result
    return  str(sum)
```

We are adding an attribute to the span in the tracing start method, and in the roll\_sum function, we obtain the current span and then add an event per roll. Events are commonly used like this to emit log events and hold exception information.

We want to roll multiple times, so this time, we will pass rolls=2 via curl. You can use the following command:

```shell
curl 'http://127.0.0.1:5000/roll?sides=10&rolls=2'
```

The tracing output will now look something like this:

```json
{
    "name": "server_request",
    "context": {
        "trace_id": "0x8c70746f079e4d03b4e23cf2b6886e5b",
        "span_id": "0x2505a6e946712b9c",
        "trace_state": "[]"
    },
    "kind": "SpanKind.INTERNAL",
    "parent_id": null,
    "start_time": "2022-03-11T02:42:56.882101Z",
    "end_time": "2022-03-11T02:42:56.882243Z",
    "status": {
        "status_code": "UNSET"
    },
    "attributes": {
        "endpoint": "/roll"
    },
    "events": [
        {
            "name": "log",
            "timestamp": "2022-03-11T02:42:56.882216Z",
            "attributes": {
                "roll.sides": 10,
                "roll.result": 3
            }
        },
        {
            "name": "log",
            "timestamp": "2022-03-11T02:42:56.882231Z",
            "attributes": {
                "roll.sides": 10,
                "roll.result": 4
            }
        }
    ],
    "links": [],
    "resource": {
        "telemetry.sdk.language": "python",
        "telemetry.sdk.name": "opentelemetry",
        "telemetry.sdk.version": "1.9.1",
        "service.name": "unknown_service"
    }
}
```

We can see an attribute has been set—letting us know the endpoint—and we can also see two events telling us the output of our two rolls and the time they were rolled.

## Instrumenting the App Automatically Using OpenTelemetry Libraries

Looking at the previous example, there are many attributes that could be added from the HTTP request. Rather than do this manually, we can use auto-instrumentation to do it standardly. Open Telemetry auto-instrumentation is instrumentation produced without code changes, often through monkey patching or bytecode injection. As previously mentioned, the feature only supports a few languages, so far [Python](https://opentelemetry.io/docs/instrumentation/python/automatic/), [Java](https://opentelemetry.io/docs/instrumentation/java/automatic/), [Node](https://opentelemetry.io/docs/instrumentation/js/), [Ruby](https://opentelemetry.io/docs/instrumentation/ruby/automatic/), and [.NET](https://opentelemetry.io/docs/instrumentation/net/automatic/) (the latter requires some minimal code changes to enable auto-instrumentation).

Auto-instrumentation isn’t omnipotent, nor is it as simple as a span per function. Instead, it’s custom implemented for a number of frameworks in a meaningful way. This is why you need to check if your language and framework are supported (Python Flask is, check out the others [on this GitHub repo](https://github.com/open-telemetry/opentelemetry-python-contrib/tree/main/instrumentation)!).

We will need to install the `opentelemetry-instrumentation-flask` package through our Python package manager to enable auto-instrumentation. Another option is running `opentelemetry-bootstrap -a install`, which will install auto-instrumentation packages for all Python frameworks that support it.

```shell
opentelemetry-bootstrap -a install 
```

To run with auto-instrumentation, we pass the method we use to run the script (in this case, Flask run) and any arguments to the `opentelemetry-instrument` command. We can do this with the original version of our code from the first example (that is, without any mention of OpenTelemetry).

Copy the code into app.py and run Flask using this new method:

```shell
opentelemetry-instrument --traces_exporter console \
 flask run
```

We are passing the processor using the `traces_exporter` flag, which moves this configuration from the codebase into the application or container runtime. We will be outputting to the console again.

Hit the endpoint with curl again, and you will see the following automatically generated tracing output:

```json
{
    "name": "/roll",
    "context": {
        "trace_id": "0xa0e68f2c6febcc2ce392871264520cae",
        "span_id": "0x9731cb56a5d68bc2",
        "trace_state": "[]"
    },
    "kind": "SpanKind.SERVER",
    "parent_id": null,
    "start_time": "2022-03-11T03:05:04.487693Z",
    "end_time": "2022-03-11T03:05:04.488611Z",
    "status": {
        "status_code": "UNSET"
    },
    "attributes": {
        "http.method": "GET",
        "http.server_name": "127.0.0.1",
        "http.scheme": "http",
        "net.host.port": 5000,
        "http.host": "127.0.0.1:5000",
        "http.target": "/roll?sides=10&rolls=1",
        "net.peer.ip": "127.0.0.1",
        "http.user_agent": "curl/7.77.0",
        "net.peer.port": 53603,
        "http.flavor": "1.1",
        "http.route": "/roll",
        "http.status_code": 200
    },
    "events": [],
    "links": [],
    "resource": {
        "telemetry.sdk.language": "python",
        "telemetry.sdk.name": "opentelemetry",
        "telemetry.sdk.version": "1.9.1",
        "telemetry.auto.version": "0.28b1",
        "service.name": "unknown_service"
    }
}
```

The output is similar to before, with a single trace containing a single span—but now we have a list of attributes that describe (from a Flask point of view) what is actually happening. We can see it was a GET request, via HTTP, to ‘/random,’ which came from the local 127.0.0.1 IP address. This comes for free—and has been defined in the `opentelemetry-instrumentation-flask` package.

This demonstrates the two key-value propositions of automatic instrumentation:

-   OpenTelemetry supplies what they consider to be best practice implementations for frameworks, creating spans as needed. Such removes the need for a developer to try and decide on the relevant attributes to include in each span.
-   OpenTelemetry configuration (like which processor to send to) can be injected without modifying your code. In this case, we are sending to the console, but this could be changed to Jaeger or an OpenTelemetry processor by modifying the command line arguments.

## Mixing Things Up: Combining Manual and Auto-Instrumentation

But what if we want to have a mix of auto-instrumentation and manual instrumentation?

That’s possible, too. Let’s imagine we want to create a span for the roll\_sum function and then attach the events from above. We can do this with a subset of the boilerplate we initially needed.

How? Replace your app.rs with the following code:

```Python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from random import randint
from flask import Flask, request

provider = TracerProvider()
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

app = Flask(__name__)

@app.route("/roll")
def roll():
    sides = int(request.args.get('sides'))
    rolls = int(request.args.get('rolls'))
    return roll_sum(sides,rolls)


def roll_sum(sides, rolls):
    with tracer.start_as_current_span("roll_sum"):  
        span = trace.get_current_span()
        sum = 0
        for r in range(0,rolls):
            result = randint(1,sides)
            span.add_event( "log", {
                "roll.sides": sides,
                "roll.result": result,
            })
            sum += result
        return  str(sum)
```

We are now applying manual instrumentation to the `roll_sum` function as previously.

That will create two spans: a parent representing the `/roll` route (and is auto-implemented), one child representing the `roll_sum` function, and an event per roll attached. We have removed any reference to a processor from the setup code.

And now, when we use the following command to rerun our application, it will be automatically injected.

```shell
opentelemetry-instrument --traces_exporter console \
 flask run
```

Now use curl to request the endpoint with two rolls:

```shell
curl 'http://127.0.0.1:5000/roll?sides=10&rolls=2'
```

And you will see output similar to the following emitted by the server to the console:

```json
{
    "name": "roll_sum",
    "context": {
        "trace_id": "0x56822e51ee80474126f186a246f522d8",
        "span_id": "0xe6a230f1367bfc95",
        "trace_state": "[]"
    },
    "kind": "SpanKind.INTERNAL",
    "parent_id": "0xdb33f044f5b450d5",
    "start_time": "2022-03-11T03:19:07.632525Z",
    "end_time": "2022-03-11T03:19:07.632589Z",
    "status": {
        "status_code": "UNSET"
    },
    "attributes": {},
    "events": [
        {
            "name": "log",
            "timestamp": "2022-03-11T03:19:07.632563Z",
            "attributes": {
                "roll.sides": 10,
                "roll.result": 4
            }
        },
        {
            "name": "log",
            "timestamp": "2022-03-11T03:19:07.632578Z",
            "attributes": {
                "roll.sides": 10,
                "roll.result": 3
            }
        }
    ],
    "links": [],
    "resource": {
        "telemetry.sdk.language": "python",
        "telemetry.sdk.name": "opentelemetry",
        "telemetry.sdk.version": "1.9.1",
        "telemetry.auto.version": "0.28b1",
        "service.name": "unknown_service"
    }
}
{
    "name": "/roll",
    "context": {
        "trace_id": "0x56822e51ee80474126f186a246f522d8",
        "span_id": "0xdb33f044f5b450d5",
        "trace_state": "[]"
    },
    "kind": "SpanKind.SERVER",
    "parent_id": null,
    "start_time": "2022-03-11T03:19:07.630657Z",
    "end_time": "2022-03-11T03:19:07.632826Z",
    "status": {
        "status_code": "UNSET"
    },
    "attributes": {
        "http.method": "GET",
        "http.server_name": "127.0.0.1",
        "http.scheme": "http",
        "net.host.port": 5000,
        "http.host": "127.0.0.1:5000",
        "http.target": "/roll?sides=10&rolls=2",
        "net.peer.ip": "127.0.0.1",
        "http.user_agent": "curl/7.77.0",
        "net.peer.port": 53607,
        "http.flavor": "1.1",
        "http.route": "/roll",
        "http.status_code": 200
    },
    "events": [],
    "links": [],
    "resource": {
        "telemetry.sdk.language": "python",
        "telemetry.sdk.name": "opentelemetry",
        "telemetry.sdk.version": "1.9.1",
        "telemetry.auto.version": "0.28b1",
        "service.name": "unknown_service"
    }
}
```

We can see that our `roll_sum` span lists our route span as its parent!

## What About Exceptions?

One other benefit that comes for free with auto-instrumentation is reporting information about exceptions. By changing the number of rolls in the curl command to a non-numeric value and hitting our auto-instrumented Flask server again, we will see a trace that contains an error event that describes the issue, including a traceback!

Without stopping the server, use curl to request the endpoint with some bad data:

```shell
curl 'http://127.0.0.1:5000/roll?sides=10&rolls=test'
```

And you will see output similar to the following emitted by the server to the console:

```json
{
    "name": "/roll",
    "context": {
        "trace_id": "0x465e01653dc7bda27572df93a6a17921",
        "span_id": "0x5626c188ddd93853",
        "trace_state": "[]"
    },
    "kind": "SpanKind.SERVER",
    "parent_id": null,
    "start_time": "2022-03-17T05:47:48.163349Z",
    "end_time": "2022-03-17T05:47:48.171841Z",
    "status": {
        "status_code": "ERROR",
        "description": "ValueError: invalid literal for int() with base 10: 'test'"
    },
    "attributes": {
        "http.method": "GET",
        "http.server_name": "127.0.0.1",
        "http.scheme": "http",
        "net.host.port": 5000,
        "http.host": "127.0.0.1:5000",
        "http.target": "/roll?sides=10&rolls=test",
        "net.peer.ip": "127.0.0.1",
        "http.user_agent": "curl/7.77.0",
        "net.peer.port": 61368,
        "http.flavor": "1.1",
        "http.route": "/roll",
        "http.status_code": 500
    },
    "events": [
        {
            "name": "exception",
            "timestamp": "2022-03-17T05:47:48.171825Z",
            "attributes": {
                "exception.type": "ValueError",
                "exception.message": "invalid literal for int() with base 10: 'test'",
                "exception.stacktrace": "Traceback (most recent call last):\n  File \"/Users/james/otel-instrumentation/lib/python3.8/site-packages/opentelemetry/trace/__init__.py\", line 562, in use_span\n    yield span\n  File \"/Users/james/otel-instrumentation/lib/python3.8/site-packages/flask/app.py\", line 2073, in wsgi_app\n    response = self.full_dispatch_request()\n  File \"/Users/james/otel-instrumentation/lib/python3.8/site-packages/flask/app.py\", line 1518, in full_dispatch_request\n    rv = self.handle_user_exception(e)\n  File \"/Users/james/otel-instrumentation/lib/python3.8/site-packages/flask/app.py\", line 1516, in full_dispatch_request\n    rv = self.dispatch_request()\n  File \"/Users/james/otel-instrumentation/lib/python3.8/site-packages/flask/app.py\", line 1502, in dispatch_request\n    return self.ensure_sync(self.view_functions[rule.endpoint])(**req.view_args)\n  File \"/Users/james/otel-instrumentation/app.py\", line 16, in roll\n    rolls = int(request.args.get('rolls'))\nValueError: invalid literal for int() with base 10: 'test'\n",
                "exception.escaped": "False"
            }
        }
    ],
    "links": [],
    "resource": {
        "telemetry.sdk.language": "python",
        "telemetry.sdk.name": "opentelemetry",
        "telemetry.sdk.version": "1.10.0",
        "telemetry.auto.version": "0.29b0",
        "service.name": "unknown_service"
    }
}
```

## The Verdict

OpenTelemetry is a fairly new technology that aims to consistently provide metrics, logs, and traces across implemented languages. It separates itself from the downstream storage and query layers, allowing these implementations to be mixed and matched or changed at a later date.

As we have seen, the OpenTelemetry Python SDK provides both manual and automatic instrumentation options for traces, which can also be combined as needed. When you use auto-instrumentation with a supported framework, a predefined set of spans will be created for you and populated with relevant attributes (including error events when exceptions occur).
