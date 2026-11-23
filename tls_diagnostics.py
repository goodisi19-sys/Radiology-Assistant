"""Privacy-preserving certificate diagnostics. Never authorize a bad certificate."""
from PySide6.QtNetwork import QSslCertificate


def reject_and_describe(error):
    error.rejectCertificate()
    host = error.url().host()[:253]
    code = getattr(error.type(), 'name', str(error.type()))
    issuers = []
    for certificate in error.certificateChain():
        names = certificate.issuerInfo(QSslCertificate.SubjectInfo.CommonName)
        if names:
            issuer = ' '.join(names).replace('\n', ' ')[:160]
            if issuer not in issuers:
                issuers.append(issuer)
    return (f'TLS: {host}; {code}; издатель: '+('; '.join(issuers) or 'не указан')+
            '. Сертификат отклонён. Проверьте доверие сертификатам с администратором; '
            'локальный анализ продолжает работать.')
