{{- define "crypto-radar.name" -}}
crypto-radar
{{- end -}}

{{- define "crypto-radar.labels" -}}
app.kubernetes.io/name: {{ include "crypto-radar.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}
