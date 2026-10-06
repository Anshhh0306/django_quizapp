import re

# Students: 2 letters + 4 digits (AD3919). Staff: name-style (shantini). Compared after lowercasing.
STUDENT_RE = re.compile(r'^[a-z]{2}\d{4}@srmist\.edu\.in$')
STAFF_RE = re.compile(r'^[a-z][a-z0-9._-]{0,63}@srmist\.edu\.in$')  # no '+', so no plus-alias duplicates; at most 64 before the @ (the username column holds 150)
TEACHERS_GROUP = 'Teachers'
STUDENTS_GROUP = 'Students'  # puts an account with ANY address among the students (test accounts); a register-number address needs no group


def is_student(user):
    """A register-number address, or a member of the Students group."""
    return bool(STUDENT_RE.match(user.email.lower())) or user.groups.filter(name=STUDENTS_GROUP).exists()


def is_teacher(user):
    # Teacher status is never inferred from the email: a superadmin adds the user to this group.
    return user.groups.filter(name=TEACHERS_GROUP).exists()


def role_of(user):
    """admin (a superuser) comes first, then student (address or group), then teacher (group), else pending. The groups are read in one query."""
    if user.is_superuser:
        return 'admin'
    if STUDENT_RE.match(user.email.lower()):
        return 'student'
    groups = set(user.groups.values_list('name', flat=True))
    if STUDENTS_GROUP in groups:
        return 'student'
    return 'teacher' if TEACHERS_GROUP in groups else 'pending'
