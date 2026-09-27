employee = {"id": "EMP-101", "name":"Asha"}

tickets = [
    {"id": "TCK-1001", "employee_id": "EMP-101", "status":"open"},
    {"id": "TCK-1002", "employee_id": "EMP-102", "status":"closed"},
    ] 

def can_view_ticket(employee_id,ticket):
    return ticket["employee_id"] == employee_id

for ticket in tickets:
    if can_view_ticket(employee["id"], ticket):
        print(ticket["id"], "allowed")
    else:
        print(ticket["id"], "denied")

