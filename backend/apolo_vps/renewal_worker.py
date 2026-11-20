import json
from .accounts import process_due_renewals

if __name__ == "__main__":
    print(json.dumps(process_due_renewals(), sort_keys=True))
