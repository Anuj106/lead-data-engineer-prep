#validating closure understanding

def create_validator(min_value):
    def validate(value):
        return value >= min_value
    return validate

validate_age = create_validator(18)
validate_salary = create_validator(10000)

a=validate_age(25)
b=validate_salary(150000)
print(a)
print(b)

#### retyr with closure/ decorator

def retry(max_retries):
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise e
        return wrapper
    return decorator


@retry(max_retries=1)
def greet():print("Hello World")
greet()


#### example with anaol of a guard being a decorator whpo checks the badge before allowing access to a person

def guard(room):                      # you hand over the room
    def check_badge(person):          # this runs on every visit
        print("Checking badge...")
        return room(person)           # then lets them into the real room
    return check_badge

@guard
def meeting_room(person):
    print(f"{person} is in the meeting")

meeting_room("Asha")
