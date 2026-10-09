from email.message import EmailMessage
import os
import secrets
import smtplib
import ssl


def delivery_mode(config):
    return "smtp" if config.mail_host else "unavailable" if config.live else "local_file"


def deliver(config, email: str, kind: str, code: str):
    message = EmailMessage()
    message["From"] = config.mail_from or "test@saveany.invalid"
    message["To"] = email
    message["Subject"] = "SaveAny 邮箱验证" if kind == "verify" else "SaveAny 重置密码"
    message.set_content(f"在 SaveAny 本机工具的账号窗口中输入以下{'验证' if kind == 'verify' else '重置'}码：\n\n{code}\n\n30 分钟内有效，仅可使用一次。请勿转发。若不是你发起，请忽略此邮件。")
    if config.mail_host:
        with smtplib.SMTP(config.mail_host, config.mail_port, timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(config.mail_user, config.mail_password)
            smtp.send_message(message)
    else:
        if config.live:
            raise RuntimeError("Production email unavailable")
        config.mail_directory.mkdir(parents=True, exist_ok=True)
        file = config.mail_directory / f"{secrets.token_hex(12)}.eml"
        descriptor = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(message.as_string())
