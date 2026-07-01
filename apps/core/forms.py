from allauth.account.forms import LoginForm, SignupForm
from django import forms

from apps.core.choices import AgentApiKeyAccessLevel
from apps.core.models import AgentApiKey, Profile
from apps.core.services import normalize_agent_api_key_access_level, normalize_agent_api_key_name
from apps.core.utils import DivErrorList


class CustomSignUpForm(SignupForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.error_class = DivErrorList


class CustomLoginForm(LoginForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.error_class = DivErrorList


class ProfileUpdateForm(forms.ModelForm):
    first_name = forms.CharField(max_length=30)
    last_name = forms.CharField(max_length=30)
    email = forms.EmailField()

    class Meta:
        model = Profile
        fields = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user:
            self.fields["first_name"].initial = self.instance.user.first_name
            self.fields["last_name"].initial = self.instance.user.last_name
            self.fields["email"].initial = self.instance.user.email

    def save(self, commit=True):
        profile = super().save(commit=False)
        user = profile.user
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
            profile.save()
        return profile


class AgentApiKeyCreateForm(forms.Form):
    name = forms.CharField(
        max_length=80,
        label="App or agent name",
        help_text=(
            "Use an app name or AI agent name. Rowset shows this name in dataset change history."
        ),
    )
    access_level = forms.ChoiceField(
        choices=AgentApiKeyAccessLevel.choices,
        initial=AgentApiKeyAccessLevel.READ_WRITE,
        label="Permission",
        required=False,
    )

    def __init__(self, *args, profile=None, **kwargs):
        self.profile = profile
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = normalize_agent_api_key_name(self.cleaned_data["name"])
        if (
            self.profile
            and AgentApiKey.objects.filter(
                profile=self.profile,
                name=name,
                revoked_at__isnull=True,
            ).exists()
        ):
            raise forms.ValidationError("An API key with this name already exists.")
        return name

    def clean_access_level(self):
        try:
            return normalize_agent_api_key_access_level(self.cleaned_data["access_level"])
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc
