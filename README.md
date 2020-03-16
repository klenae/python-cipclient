# python-cipclient
[![License](https://img.shields.io/github/license/klenae/python-cipclient)](https://github.com/klenae/python-cipclient/blob/master/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/python-cipclient)](https://pypi.org/project/python-cipclient/)
![Python Version](https://img.shields.io/pypi/pyversions/python-cipclient)
![PyPI - Wheel](https://img.shields.io/pypi/wheel/python-cipclient)
[![Black](https://img.shields.io/badge/code%20style-black-000000)](https://github.com/ambv/black)
[![Issues](https://img.shields.io/github/issues/klenae/python-cipclient)](https://github.com/klenae/python-cipclient/issues)

A Python module for communicating with Crestron control processors via the
Crestron-over-IP (CIP) protocol.

---

#### _NOTICE: This module is not produced, endorsed, maintained or supported by Crestron Electronics Incorporated. 'XPanel', 'Smart Graphics' and 'SIMPL Windows' are all trademarks of Crestron. The author is not affiliated in any way with Crestron with the exception of owning and using some of their hardware._

This is a Python-based socket client that facilitates communications with a Crestron control processor using the Crestron-over-IP (CIP) protocol. Familiarity with and access to Crestron's development tools, processes and terminology are required to configure the control processor in a way that allows this module to be used. 


## Installation
This module is available throught the [Python Package Index](https://pypi.org/project/python-cipclient/), and can be installed using the pip package-management system:

`pip install python-cipclient`

## Usage and API
This module works by connecting to an "XPanel 2.0 Smart Graphics" symbol defined in a SIMPL Windows program.  Once the control processor has been programmed accordingly, you can communicate with it using the API as described below.

### Getting Started
Here is a simple example that demonstrates setting and getting join states using this module.

```python
import cipclient

# set up the client to connect to hostname "processor" at IP-ID 0x0A
cip = cipclient.CIPSocketClient("processor", 0x0A)

# initiate the socket connection and start worker threads
cip.start()

# you can force this client and the processor to resync using an update request
cip.update_request()  # note that this also occurs automatically on first connection

# for joins coming from this client going to the processor
cip.set("d", 1, 1)  # set digital join 1 high
cip.set("d", 132, 0)  # set digital join 132 low
cip.set("a", 12, 32456)  # set analog join 12 to 32456
cip.set("s", 101, "Hello Crestron!")  # set serial join 101 to "Hello Crestron!"
cip.pulse(2)  # pulses digital join 2 (sets it high then immediately sets it low again)
cip.press(3)  # emulates a touchpanel button press on digital join 3 (stays high until released)
cip.release(3)  # emulates a touchpanel button release on digital join 3

# for joins coming from the processor going to this client
digital_34 = cip.get("d", 34)  # returns the current state of digital join 34
analog_109 = cip.get("a", 109)  # returns the current state of analog join 109
serial_223 = cip.get("s", 223)  # returns the current state of serial join 223

# you should really subscribe to incoming (processor > client) joins rather than polling
def my_callback(sigtype, join, state):
    print(f"{sigtype} {join} : {state}")

cip.subscribe("d", 1, my_callback)  # run 'my_callback` when digital join 1 changes

# this will close the socket connection when you're finished
cip.stop()
```

### Detailed Descriptions
`start()` should be called once after instantiating a CIPSocketClient to initiate the socket connection and start the required worker threads.  When the socket connection is first established, the standard CIP registration and update request procedures are performed automatically.  

`stop()` should be called once when you're finished with the CIPSocketClient to close the socket connection and shut down the worker threads.

`update_request()` can be used while connected to initiate the update request (two-way synchronization) procedure.

`set(sigtype, join, value)` is used to set the state of joins coming from the CIPSocketClient as seen by the control processor.  `sigtype` can be `"d"` for digital joins, `"a"` for analog joins or `"s"` for serial joins.  `join` is the join number.  `value` can be `0` or `1` for digital joins, `0` - `65535` for analog joins or a string for serial joins.

`press(join)` sets digital `join` high using special CIP processing intended for joins that should be automatically reset to a low state if the connection is broken or times out unexpectedly.   

`release(join)` sets digital `join` low.  Used in conjunction with `press()`.

`pulse(join)` sends a momentary pulse on digital `join` by setting the join high then immediately setting it low again.

`get(sigtype, join, direction="in")` returns the current state of the specified join as it exists within the CIPSocketClient's state machine.  (Join changes are always sent from the control processor to the client at the moment they change.  The client tracks all incoming messages and stores the current state of every join in its state machine.)  `sigtype` can be `"d"`, `"a"` or `"s"` for digital, analog or serial signals.  `join` is the join number.  `direction` is an optional argument, which is set to `"in"` by default to retrieve the state of incoming joins.  If you need to get the last state of a join that was sent from the client to the control processor, you can specify `direction="out"`.

`subscribe(sigtype, join, callback, direction="in")` is used to specify a callback function that should be called any time the specified join changes state.  `sigtype`, `join` and `direction` function the same as in the `get` method described above.  `callback` is the name of the function that should be called on each change.  `sigtype`, `join` and `state` will be passed to the specified callback in that order.  See the example above in the *Getting Started* section.

