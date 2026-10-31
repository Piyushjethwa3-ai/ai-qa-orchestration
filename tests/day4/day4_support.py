"""
Fake-SDK response builders shared by the Day 4 tests.

These live in a module with a UNIQUE name on purpose. Tests used to do `from conftest import ...`, but every
conftest.py is loaded under the module name "conftest", so which file that name meant depended on which
conftest.py pytest had loaded last (Day 3's, when Day 3 was collected after Day 4). That made three tests
fail whenever Day 4 ran before Day 3. A uniquely named module means the same file in every execution order.
"""

from types import SimpleNamespace


def sdk_response(text, *, usage=True, model="gen-model-2026"):
    return SimpleNamespace(
        model=model, status="completed", incomplete_details=None,
        output=[SimpleNamespace(type="message", content=[SimpleNamespace(type="output_text", text=text)])],
        usage=SimpleNamespace(input_tokens=11, output_tokens=7, total_tokens=18) if usage else None)


def refusal_response():
    return SimpleNamespace(model="gen-model-2026", status="completed", incomplete_details=None, usage=None,
                           output=[SimpleNamespace(type="message", content=[SimpleNamespace(type="refusal", refusal="No.")])])
