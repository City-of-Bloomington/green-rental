from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

from building.models import Building, Unit, UTILITY_TYPES

from source.models import Source
from person.models import Person
from city.models import City

from jsonfield import JSONField

#When exporting data for House Facts Data Standard, convert to following:
#water, sewer, storm water, gas, electricity, trash, recycling, compost, data, video, phone, data+video, video+phone, data+phone, data+video+phone, wifi

#It would be nice to keep the nomenclature common across cities for analytical purposes.

def add_utility_average_to_unit(unit, average, utility_type):
    """
    helper to add the average as this month's value
    for the specified utility_type
    to the specified unit

    this way averages are tracked over time as a UtilitySummary
    in case that is the only utility data supplied

    otherwise, average would be updated and overwritten at the Unit level
    every time it changes.
    that seems lossy...
    this is a way to track it.

    if multiple average values are supplied in the same month
    the last one will overwrite the previous one.

    a lot of functional overlap with
    utility.views.edit and utility.views.save_json

    not seeing an easy way to abstract functionality from them yet. 
    """
    provider = None

    city_provider_options = CityServiceProvider.objects.filter(city=unit.building.city)
    matches = []
    for cpo in city_provider_options:
        for utility in cpo.provider.utilities.all():
            if utility.type == utility_type:
                matches.append(cpo.provider)

    #print "MATCHES: %s" % matches

    if len(matches):
        #first one should be default
        provider = matches[0]
    else:
        #print "error finding utility_provider: %s matches" % len(provider_options)
        pass

    this_month = timezone.now().replace(day=1)

    #look up the corresponding UtilitySummary model object
    options = UtilitySummary.objects.filter(building=unit.building, unit=unit, type=utility_type, start_date=this_month)

    updated = False
    unit_updated = False

    if options.count():
        #"Updating existing entry:"
        summary = subset[0]

        #if different, apply and save changes
        if summary.cost != average:
            summary.cost = average
            updated = True

        if provider:
            if summary.provider != provider:
                summary.provider = provider
                updated = True

    else:
        summary = UtilitySummary()
        summary.building = unit.building
        summary.unit = unit
        summary.type = utility_type

        #ideally, should set one of these
        #we can only set here if we found a provider above
        if provider:
            summary.provider = provider

        summary.start_date = this_month
        summary.cost = average
        updated = True

    if updated:
        #TODO:
        #consider logging any changes to prevent data loss
        summary.save()
        #print "Changes saved"
        unit_updated = True

    #going to leave this up to caller:
    ## if unit_updated:
    ##     #this takes care of updating corresponding averages and scores
    ##     unit.save_and_update(request)

    return unit_updated



class StatementUpload(models.Model):
    """
    2014.10.16 15:03:56 
    DEPRECATED...
    start using Statement object instead...
    will keep around for old form that uses it, until that process is retired
    
    object to represent an uploaded statement.
    This starts off as unprocessed data,
    and eventually gets converted into one or more
    corresponding UtilitySummary objects
    """

    #if a file (statement) was uploaded, this is where it will be stored:
    blob_key = models.TextField()

    #rather than use a ForeignKey, keep it as text
    #this way users can upload data for cities not in system yet
    #and we can gauge interest for the service in other cities.
    city_tag = models.CharField(max_length=150)

    #eventually duplicated in generated Utility objects
    #but if it is supplied at the time of the upload, can keep track of it here
    building_address = models.CharField(max_length=200)

    unit_number = models.CharField(max_length=20, blank=True, null=True)
    #just using strings, in case the supplied value is not in the database yet 
    #building = models.ForeignKey(Building, blank=True)
    #unit = models.ForeignKey(Unit, blank=True, null=True)  

    #track what IP address supplied the statement...
    #might help if someone decides to upload garbage
    #especially if logins are not required
    ip_address = models.GenericIPAddressField()

    added = models.DateTimeField('date published', auto_now_add=True)

    vendor = models.CharField(max_length=200, blank=True)

    type = models.CharField(max_length=12, choices=UTILITY_TYPES, default="electricity")


    #keep track of any unit details in an unprocessed upload here
    #eventually these should be added to the actual building/unit
    #
    #format as a json blob
    #include values such as:
    # - move in date (instead of months lived) DateField
    # - square feet of unit
    # - how many bedrooms
    # - programmable thermostat?
    #unit_details = models.TextField(blank=True)
    unit_details = JSONField(blank=True)

    #when the person moved in to the unit
    #eventually associate this with a BuildingPerson?
    move_in = models.DateField('move in date', blank=True, null=True)

    #this could go with the unit as well:
    #other energy sources:
    #list? text?
    energy_sources = JSONField(blank=True, null=True)
    
    #ways of saving energy at residence: (text)
    energy_strategy = models.TextField(blank=True, null=True)

    #if the person has logged in with an account at the time of upload,
    #capture that here
    user = models.ForeignKey(User, blank=True, null=True)

    #otherwise, if they provide an email address for future contact,
    #update that here:
    person_email = models.EmailField(max_length=200, blank=True, null=True)

    #processing (extracting and importing data) may need to happen separately:
    processed = models.BooleanField(default=False)



class ServiceProvider(models.Model):
    """
    AKA Vendor, Utility
    """
    #TODO: name unique?
    #gotta have a name:
    name = models.CharField(max_length=200)
    instructions = models.TextField(blank=True)
    website = models.TextField(blank=True)
    #website = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=30)

class ServiceUtility(models.Model):
    """
    many-to-one for the services / utilities that a ServiceProvider provides
    """
    provider = models.ForeignKey(ServiceProvider, related_name="utilities")
    #as long as we're consistent in the application,
    #shouldn't need a separate table for this
    type = models.CharField(max_length=30)

class CityServiceProvider(models.Model):
    """
    A City will have more than one ServiceProvider
    a ServiceProvider may offer services in more than one City
    this is a place to match up the two (many-to-many)
    """
    provider = models.ForeignKey(ServiceProvider)
    city = models.ForeignKey(City)
    #in case there is a city specific site:
    #(e.g. company provides service to many different cities.)
    website = models.TextField(blank=True)

class Statement(models.Model):
    """
    A simplified version of StatementUpload

    this one requires that a unit be associated with the Statment
    now that anyone can add a new building via the site,
    this doesn't seem like a restrictive requirement
    it also helps eliminate a lot of extra data associated with StatementUpload

    Represent an uploaded statement.
    This starts off as unprocessed data,
    and gets converted into one or more corresponding UtilitySummary objects
    """

    #if a file (statement) was uploaded, this is where it will be stored:
    blob_key = models.TextField()

    #original name of file:
    original_filename = models.CharField(max_length=200, blank=True, null=True)
    
    #unit_number = models.CharField(max_length=20, blank=True, null=True)
    #just using strings, in case the supplied value is not in the database yet 

    #don't think we need the building here...
    #will always be at least one unit per building,
    #and unit links to building
    #building = models.ForeignKey(Building, blank=True)
    
    unit = models.ForeignKey(Unit)  

    #track what IP address supplied the statement...
    #might help if someone decides to upload garbage
    #especially if logins are not required
    ip_address = models.GenericIPAddressField()

    added = models.DateTimeField('date published', auto_now_add=True)

    #these correspond directly to the values used in UtilitySummary

    #going to use this as an "Other" field
    #in the case when an existing ServiceProvider is not in the system
    vendor = models.CharField(max_length=200, blank=True, null=True)

    #may not be in system... not required in that case
    provider = models.ForeignKey(ServiceProvider, blank=True, null=True)

    type = models.CharField(max_length=12, choices=UTILITY_TYPES, default="electricity")

    #if the person has logged in with an account at the time of upload,
    #capture that here
    #will accept uploads from non-logged in users though
    user = models.ForeignKey(User, blank=True, null=True)

    #processing (extracting and importing data) may need to happen separately:
    #processed = models.BooleanField(default=False)
    processed = models.DateTimeField(blank=True, null=True)

    processed_by = models.ForeignKey(User, related_name="processed_statements", blank=True, null=True)


class UtilitySummary(models.Model):
    """
    AKA Reading, Service

    A summary of utility service received for a given address.

    adapted from:
    https://docs.google.com/document/d/1bwcGTgGkdnu8LjjYiyg6YBocwdzEsk5mqeU9GhjW4so/edit?pli=1

    this can also reference the original uploaded statement
    """

    #not going to require building and unit...
    #can set it if it is supplied through the app
    #or can go look it up later once the statement is processed (after upload)

    #in order for it to show up on a map, it will need to be set.
    
    #building_id = string (required=yes)
    building = models.ForeignKey(Building)

    #parcel_id = string (required=no)

    #Required if reading is for specific unit in a multi-unit building.
    #A unit name or number is acceptable.
    #if every building has at least one unit, this is all that is needed.
    #probably easier to keep both though
    #unit_number = string (required=no)
    #unit = models.ForeignKey(Unit, related_name="utilties")
    unit = models.ForeignKey(Unit)

    #if this was taken from a statement, associate it here
    #(but it could be added directly via a form... manually add bill, etc)
    statement = models.ForeignKey(Statement, blank=True, null=True)

    #source of report.
    #could be: city data, utility data, or crowd-sourced public reporting
    #reading_source = string (required=yes)
    #source = models.ForeignKey(Source)
    #would like to leave this null if it's from the web
    source = models.ForeignKey(Source, blank=True, null=True)

    #One of the following categories (water, sewer, storm water, gas, electricity, trash, recycling, compost, data, video, phone, data+video, video+phone, data+phone, data+video+phone, wifi). It would be nice to keep the nomenclature common across cities for analytical purposes.
    #reading_type = string (required=yes)
    type = models.CharField(max_length=12, choices=UTILITY_TYPES, default="electricity")

    #if vendor is in system, use provider attribute
    #if it is specified as Other, use vendor
    
    #Vendor for utility service. Examples: City of Bloomington Utilities, Comcast, AT&T, Duke Energy, etc)
    #vendor = string (required=no)
    #going to use this as an "Other" field
    #in the case when an existing ServiceProvider is not in the system
    vendor = models.CharField(max_length=200, blank=True, null=True)

    #may not be in system... not required in that case
    provider = models.ForeignKey(ServiceProvider, blank=True, null=True)

    #Start of the utility service billing period in YYYY-MM-DD format
    #reading_period_start_date = date (required=no)
    start_date = models.DateTimeField()

    #Last day of the utility service billing period in YYYY-MM-DD format
    #to simplify data entry, will only require a start date...
    #can infer end date
    #reading_period_end_date = date (required=no)
    end_date = models.DateTimeField(blank=True, null=True)

    #Billing cost for utility consumption.
    #reading_cost = currency (required=no)
    cost = models.FloatField(blank=True, null=True)

    #Common units acceptable (gallon, liter, kW, lb, kg, etc)
    #reading_unit = string (required=yes)
    #aka increment
    #not going with "unit" to avoid confusion with a unit in a building
    unit_of_measurement = models.CharField(max_length=50, blank=True)

    #Numerical value of reading (may need to consider other options like (on, off) for acceptable values
    #reading_value = number (required=yes)
    #aka value
    amount = models.FloatField(blank=True, null=True)


    #Date of the reading event in YYYY-MM-DD format.
    #reading_date = date (required=yes)
    added = models.DateTimeField('date published', auto_now_add=True)


