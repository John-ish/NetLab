class DatabaseError(Exception):
    pass


class SecretError(DatabaseError):
    pass
