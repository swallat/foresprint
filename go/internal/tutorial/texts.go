package tutorial

// german are the texts of the team in German; everything else stays English.
var german = map[string]string{
	"Self-service 2.0":                      "Self-Service 2.0",
	"Concept approved":                      "Konzept freigegeben",
	"Beta for customers":                    "Beta für Kunden",
	"Launch":                                "Einführung",
	"E-invoice":                             "E-Rechnung",
	"Invoice format":                        "Rechnungsformat",
	"Sending":                               "Versand",
	"Single sign-on":                        "Einmalanmeldung",
	"SSO live":                              "Einmalanmeldung ist live",
	"Dark mode":                             "Dunkles Design",
	"agreed with marketing":                 "mit dem Marketing abgestimmt",
	"rough guess until refinement":          "grobe Schätzung bis zur Verfeinerung",
	"needs production access":               "braucht Zugang zum Produktivsystem",
	"Concept for the new self-service area": "Konzept für den neuen Self-Service-Bereich",
	"Customers change their address themselves":     "Kunden ändern ihre Adresse selbst",
	"Customers download their invoices":             "Kunden laden ihre Rechnungen herunter",
	"Mobile screens for the self-service area":      "Mobile Ansichten für den Self-Service-Bereich",
	"Cancel a contract online":                      "Vertrag online kündigen",
	"Help texts and feedback form":                  "Hilfetexte und Feedback-Formular",
	"Choose the e-invoice format":                   "Format der E-Rechnung wählen",
	"Create invoices in the new format":             "Rechnungen im neuen Format erzeugen",
	"Send invoices by e-mail":                       "Rechnungen per E-Mail versenden",
	"Single sign-on: connect the identity provider": "Einmalanmeldung: Identitätsanbieter anbinden",
	"Single sign-on: migrate existing accounts":     "Einmalanmeldung: bestehende Konten umziehen",
	"Faster start of the mobile app":                "Schnellerer Start der mobilen App",
	"Export the order list as a file":               "Bestellliste als Datei exportieren",
	"Daily check of the nightly jobs":               "Tägliche Prüfung der Nachtläufe",
	"Update the build pipeline":                     "Build-Pipeline aktualisieren",
	"Dark mode for the portal":                      "Dunkles Design für das Portal",
	"Fix rounding on credit notes":                  "Rundung bei Gutschriften korrigieren",
}

func translate(lang, s string) string {
	if lang == "de" {
		if t, ok := german[s]; ok {
			return t
		}
	}
	return s
}
