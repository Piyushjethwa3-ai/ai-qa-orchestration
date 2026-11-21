"""The planner with the privileged-request flow switched on (Day 6). Same rules as the Week 5 planner,
plus: a reset request needs the employee's yes, becomes a PENDING approval, and runs only after IT approval."""

from __future__ import annotations

from app.agent.planner import Reply, RulePlanner, ToolCall, Turn, _escalate, _last
from app.agent.tools import DENIED, PENDING_APPROVAL, SUCCESS, ToolResult


class GovernedPlanner(RulePlanner):
    def _after_request_privileged_action(self, turn: Turn, result: ToolResult):
        if result.status == PENDING_APPROVAL:
            rid = result.data["request_id"]
            return Reply("PENDING_APPROVAL", f"Your request {rid} has been submitted and is waiting for IT approval. "
                         "Nothing has been reset. Ask me for its status later; I can only carry it out after IT approves.",
                         clear_pending=True, slots={"privileged_request_id": rid})
        return Reply("DENIED", "I couldn't submit the request because your confirmation is missing or no longer valid. "
                     "Nothing was submitted.", clear_pending=True)

    def _after_execute_privileged_action(self, turn: Turn, result: ToolResult):
        if result.status == SUCCESS:
            return Reply("PRIVILEGED_EXECUTED", "The tool confirmed that the simulated action was carried out: "
                         f"{result.data['result']}", clear_pending=True)
        return Reply("DENIED", "The action was not carried out. Its approval is missing, changed, expired or already "
                     "used. Nothing was changed.", clear_pending=True)

    def _privileged_status(self, turn: Turn):
        rid = turn.session.slots.get("privileged_request_id")
        result = _last(turn, "get_privileged_request_status")
        if result is None:
            return ToolCall("get_privileged_request_status", {"request_id": rid})
        if result.status != SUCCESS:
            return Reply("DENIED", "I can't show that request.")
        data = result.data
        status = data["approval_status"]
        if data["executed"] or status == "USED":
            return Reply("PRIVILEGED_STATUS", f"Request {rid} has already been carried out (simulated).")
        if status == "PENDING":
            return Reply("PRIVILEGED_STATUS", f"Request {rid} is still waiting for IT approval. Nothing has been changed.")
        if status == "REJECTED":
            return Reply("PRIVILEGED_STATUS", f"IT rejected request {rid}. Nothing has been changed.")
        if status == "EXPIRED":
            return Reply("PRIVILEGED_STATUS", f"The approval for request {rid} has expired. Nothing has been changed. "
                         "Please submit a new request.")
        proposal = {"action": "execute_privileged_action",
                    "params": {"request_id": rid, "action": data["action"], "action_params": data["action_params"]}}
        return Reply("PENDING_CONFIRMATION", f"IT has approved request {rid}. Nothing has been carried out yet. "
                     "Reply yes to carry it out (simulated) or no to cancel.", proposal=proposal)
