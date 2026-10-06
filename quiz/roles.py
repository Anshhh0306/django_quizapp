import re

# Students: 2 letters + 4 digits (AD3919). Staff: name-style (shantini). Compared after lowercasing.
STUDENT_RE = re.compile(r'^[a-z]{2}\d{4}@srmist\.edu\.in$')
STAFF_RE = re.compile(r'^[a-z][a-z0-9._-]{0,63}@srmist\.edu\.in$')  # no '+', so no plus-alias duplicates; at most 64 before the @ (the username column holds 150)
TEACHERS_GROUP = 'Teachers'


def is_student(user):
    return bool(STUDENT_RE.match(user.email.lower()))


def is_teacher(user):
    # Teacher status is never inferred from the email: a superadmin adds the user to this group.
    return user.groups.filter(name=TEACHERS_GROUP).exists()


def role_of(user):
    if user.is_superuser:
        return 'admin'
    if is_student(user):
        return 'student'
    return 'teacher' if is_teacher(user) else 'pending'
