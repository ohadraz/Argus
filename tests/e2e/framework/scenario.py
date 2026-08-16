class Scenario:
    def __init__(self):
        self.result = None

    def given(self, *steps):
        for step in steps:
            if not step():
                raise AssertionError(
                    f"Given failed: {step.__name__}"
                )

        return self

    def when(self, step):
        self.result = step()
        return self

    def then(self, assertion):
        if not assertion(self.result):
            raise AssertionError("Then assertion failed")

        return self