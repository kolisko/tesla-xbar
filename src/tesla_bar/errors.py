"""Errors responsibilities for Tesla xBar."""



class AppError(Exception):
    pass


class APIError(AppError):
    def __init__(self, status, retry_after=0):
        self.status = status
        self.retry_after = retry_after
        messages = {401: "Your session has expired. Connect your Tesla account again.",
                    402: "Set up billing in the Tesla Developer portal.",
                    403: "Tesla denied access. Check the app permissions and registration.",
                    404: "Vehicle or registration not found.",
                    408: "The vehicle is unavailable or asleep.",
                    412: "Complete the app registration in the account’s region.",
                    421: "Your account is in another region. Change the region in Settings.",
                    429: "Tesla rate limit reached. Refresh has been postponed."}
        super().__init__(messages.get(status, f"Tesla API: HTTP error {status}."))
